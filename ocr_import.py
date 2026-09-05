from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageGrab, ImageOps
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR


CARD_WIDTH = 350
CARD_HEIGHT = 105
NAME_AREA = (115, 15, 340, 55)
BM_AREA = (140, 55, 295, 102)
NAME_ROW_HEIGHT = 120
BM_ROW_HEIGHT = 100
REWARD_DETECTION_RETRY_SCALE = 3
REWARD_DETECTION_ACCEPT_CONFIDENCE = 0.80


@dataclass(frozen=True)
class RecognizedParticipant:
    name: str
    bm: int
    confidence: float


@dataclass(frozen=True)
class CardBox:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2.0


@dataclass(frozen=True)
class OcrLine:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2.0


class OcrError(RuntimeError):
    pass


_rapid_engines: dict[LangRec, RapidOCR] = {}
_reward_rapid_engine: RapidOCR | None = None
_rapid_engine_lock = threading.Lock()


def clipboard_image() -> Image.Image:
    content = ImageGrab.grabclipboard()
    if isinstance(content, Image.Image):
        return content.convert("RGB")
    if isinstance(content, list) and content:
        try:
            return Image.open(content[0]).convert("RGB")
        except (OSError, ValueError) as error:
            raise OcrError("В буфере нет изображения.") from error
    raise OcrError("В буфере нет изображения.")


def recognize_participants(image: Image.Image) -> list[RecognizedParticipant]:
    source = image.convert("RGB")
    boxes = _detect_card_boxes(source)
    if not boxes:
        raise OcrError("На изображении не найдены карточки участников.")

    name_crops: list[Image.Image] = []
    bm_crops: list[Image.Image] = []
    for box in boxes:
        card = source.crop(
            (box.left, box.top, box.right, box.bottom)
        ).resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS)
        name_crops.append(card.crop(NAME_AREA))
        bm_crops.append(card.crop(BM_AREA))

    latin_names = _recognize_name_atlas(name_crops)
    bm_values = _recognize_bm_atlas(bm_crops)
    neural_names = _recognize_name_scripts(name_crops)

    participants: list[RecognizedParticipant] = []
    for index in range(len(boxes)):
        name, name_confidence = _select_name(
            latin_names[index], neural_names[index]
        )
        bm = bm_values[index]
        if not name or bm is None:
            continue
        participants.append(
            RecognizedParticipant(
                name=name[:40],
                bm=bm,
                confidence=max(0.0, min(100.0, name_confidence)),
            )
        )
    return participants


def recognize_reward_name(image: Image.Image) -> str:
    """Recognize the single item-title line from a reward card image."""

    source = image.convert("RGB")
    if source.width < 20 or source.height < 12:
        raise OcrError("Изображение награды слишком маленькое.")

    engine = _get_reward_rapid_engine()
    candidates: list[tuple[str, float, int]] = []
    for scale in (1, REWARD_DETECTION_RETRY_SCALE):
        prepared = source
        if scale != 1:
            prepared = source.resize(
                (source.width * scale, source.height * scale),
                Image.Resampling.LANCZOS,
            )
        output = engine(
            np.asarray(prepared),
            use_det=True,
            use_cls=False,
            use_rec=True,
        )
        candidate = _select_detected_reward_title(output)
        if candidate is None:
            continue
        candidates.append(candidate)
        if candidate[1] >= REWARD_DETECTION_ACCEPT_CONFIDENCE:
            return candidate[0]

    if not candidates:
        raise OcrError("Не удалось распознать название награды.")
    return max(
        candidates,
        key=lambda candidate: (candidate[1], candidate[2]),
    )[0]


def _select_detected_reward_title(
    output: object,
) -> tuple[str, float, int] | None:
    """Select a title using detected text geometry, without a fixed crop."""

    texts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    boxes = getattr(output, "boxes", None)
    if texts is None or scores is None or boxes is None:
        return None

    detected: list[tuple[str, float, float, float, float, float]] = []
    for raw_text, raw_score, raw_box in zip(texts, scores, boxes):
        text = _clean_reward_name(str(raw_text))
        letter_count = sum(character.isalpha() for character in text)
        if letter_count < 2:
            continue
        points = np.asarray(raw_box, dtype=float).reshape(-1, 2)
        if not len(points):
            continue
        left = float(points[:, 0].min())
        right = float(points[:, 0].max())
        top = float(points[:, 1].min())
        bottom = float(points[:, 1].max())
        detected.append(
            (
                text,
                max(0.0, min(1.0, float(raw_score))),
                left,
                top,
                max(1.0, right - left),
                max(1.0, bottom - top),
            )
        )
    if not detected:
        return None

    rows: list[list[tuple[str, float, float, float, float, float]]] = []
    for item in sorted(detected, key=lambda value: value[3] + value[5] / 2):
        center_y = item[3] + item[5] / 2
        matching_row: list[tuple[str, float, float, float, float, float]] | None = None
        for row in rows:
            row_center = sum(value[3] + value[5] / 2 for value in row) / len(row)
            row_height = max(value[5] for value in row)
            if abs(center_y - row_center) <= max(row_height, item[5]) * 0.60:
                matching_row = row
                break
        if matching_row is None:
            rows.append([item])
        else:
            matching_row.append(item)

    title_candidates: list[tuple[str, float, int]] = []
    for row in rows:
        ordered = sorted(row, key=lambda value: value[2])
        runs: list[list[tuple[str, float, float, float, float, float]]] = []
        for item in ordered:
            if not runs:
                runs.append([item])
                continue
            previous = runs[-1][-1]
            gap = item[2] - (previous[2] + previous[4])
            if gap <= max(previous[5], item[5]) * 1.5:
                runs[-1].append(item)
            else:
                runs.append([item])
        for run in runs:
            text = _clean_reward_name(" ".join(item[0] for item in run))
            letter_count = sum(character.isalpha() for character in text)
            if letter_count < 3:
                continue
            confidence = sum(
                item[1]
                * max(1, sum(character.isalpha() for character in item[0]))
                for item in run
            ) / letter_count
            title_candidates.append((text, confidence, letter_count))

    if not title_candidates:
        return None
    return max(
        title_candidates,
        key=lambda candidate: (candidate[2], candidate[1]),
    )


def _detect_card_boxes(image: Image.Image) -> list[CardBox]:
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 30, 90)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    connected = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        connected, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )

    candidates: list[tuple[CardBox, float]] = []
    for contour in contours:
        left, top, width, height = cv2.boundingRect(contour)
        if width < 150 or height < 45:
            continue
        aspect_ratio = width / height
        if not 2.7 <= aspect_ratio <= 3.8:
            continue
        fill_ratio = cv2.contourArea(contour) / (width * height)
        if fill_ratio < 0.65:
            continue
        candidates.append((CardBox(left, top, width, height), fill_ratio))

    candidates.sort(
        key=lambda item: item[0].width * item[0].height,
        reverse=True,
    )
    boxes: list[CardBox] = []
    for candidate, _ in candidates:
        if any(_box_iou(candidate, existing) > 0.55 for existing in boxes):
            continue
        boxes.append(candidate)
    return _order_card_boxes(boxes)


def _box_iou(first: CardBox, second: CardBox) -> float:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)
    intersection = max(0, right - left) * max(0, bottom - top)
    if not intersection:
        return 0.0
    first_area = first.width * first.height
    second_area = second.width * second.height
    return intersection / (first_area + second_area - intersection)


def _order_card_boxes(boxes: list[CardBox]) -> list[CardBox]:
    rows: list[list[CardBox]] = []
    for box in sorted(boxes, key=lambda item: item.center_y):
        if not rows:
            rows.append([box])
            continue
        row = rows[-1]
        row_center = sum(item.center_y for item in row) / len(row)
        row_height = max(item.height for item in row)
        if abs(box.center_y - row_center) <= max(row_height, box.height) * 0.5:
            row.append(box)
        else:
            rows.append([box])

    ordered: list[CardBox] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda item: item.left))
    return ordered


def _prepare_text_crop(image: Image.Image) -> Image.Image:
    resized = image.resize(
        (image.width * 2, image.height * 2),
        Image.Resampling.LANCZOS,
    )
    gray = ImageOps.grayscale(resized)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageOps.invert(gray)
    return ImageEnhance.Contrast(gray).enhance(1.45)


def _make_atlas(
    crops: list[Image.Image],
    *,
    width: int,
    row_height: int,
) -> Image.Image:
    atlas = Image.new("L", (width, max(1, len(crops)) * row_height), 255)
    for index, crop in enumerate(crops):
        atlas.paste(_prepare_text_crop(crop), (10, index * row_height + 5))
    return atlas


def _recognize_name_atlas(
    crops: list[Image.Image],
) -> list[tuple[str, float]]:
    atlas = _make_atlas(crops, width=480, row_height=NAME_ROW_HEIGHT)
    lines = _parse_tsv_lines(_run_tesseract(atlas, "eng+rus"))
    grouped: list[list[OcrLine]] = [[] for _ in crops]
    for line in lines:
        index = int(line.center_y // NAME_ROW_HEIGHT)
        if 0 <= index < len(grouped) and any(char.isalpha() for char in line.text):
            grouped[index].append(line)

    result: list[tuple[str, float]] = []
    for lines_in_row in grouped:
        if not lines_in_row:
            result.append(("", 0.0))
            continue
        line = max(lines_in_row, key=lambda item: item.confidence)
        result.append((_clean_name(line.text), line.confidence))
    return result


def _recognize_bm_atlas(crops: list[Image.Image]) -> list[int | None]:
    atlas = _make_atlas(crops, width=340, row_height=BM_ROW_HEIGHT)
    lines = _parse_tsv_lines(
        _run_tesseract(atlas, "eng", digit_only=True)
    )
    grouped: list[list[int]] = [[] for _ in crops]
    for line in lines:
        index = int(line.center_y // BM_ROW_HEIGHT)
        if not 0 <= index < len(grouped):
            continue
        bm = _extract_bm(line.text)
        if bm is not None:
            grouped[index].append(bm)
    return [values[0] if values else None for values in grouped]


def _recognize_name_scripts(
    crops: list[Image.Image],
) -> list[dict[str, tuple[str, float]]]:
    engines = {
        "english": _get_rapid_engine(LangRec.EN),
        "cyrillic": _get_rapid_engine(LangRec.CYRILLIC),
        "cjk": _get_rapid_engine(LangRec.CH),
    }
    results: list[dict[str, tuple[str, float]]] = []
    for crop in crops:
        rgb = np.asarray(crop.convert("RGB"))
        variants: dict[str, tuple[str, float]] = {}
        for key, engine in engines.items():
            output = engine(
                rgb,
                use_det=False,
                use_cls=False,
                use_rec=True,
            )
            if not output.txts:
                variants[key] = ("", 0.0)
                continue
            variants[key] = (
                _clean_name(output.txts[0]),
                float(output.scores[0]) * 100.0,
            )
        results.append(variants)
    return results


def _select_name(
    tesseract: tuple[str, float],
    neural: dict[str, tuple[str, float]],
) -> tuple[str, float]:
    cjk_name, cjk_confidence = neural["cjk"]
    if _contains_cjk(cjk_name):
        return _remove_cjk_spaces(cjk_name), cjk_confidence

    cyrillic_name, cyrillic_confidence = neural["cyrillic"]
    if _contains_cyrillic(cyrillic_name) and cyrillic_confidence >= 45.0:
        return _normalize_cyrillic_candidate(cyrillic_name), cyrillic_confidence

    tesseract_name, tesseract_confidence = tesseract
    english_name, english_confidence = neural["english"]
    if _same_with_ocr_digit_ambiguity(tesseract_name, english_name):
        if any(char.isdigit() for char in english_name) and english_confidence >= 55.0:
            return english_name, english_confidence
    if tesseract_name:
        return tesseract_name, tesseract_confidence

    latin_variants = [
        neural["english"], neural["cyrillic"], neural["cjk"]
    ]
    return max(latin_variants, key=lambda item: item[1])


def _same_with_ocr_digit_ambiguity(first: str, second: str) -> bool:
    if not first or len(first) != len(second):
        return False
    ambiguous = (
        {"O", "0"},
        {"o", "0"},
        {"I", "1"},
        {"l", "1"},
    )
    for first_char, second_char in zip(first, second):
        if first_char == second_char:
            continue
        if not any({first_char, second_char} == pair for pair in ambiguous):
            return False
    return True


def _contains_cyrillic(text: str) -> bool:
    return any("\u0400" <= char <= "\u052f" for char in text)


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30ff"
        or "\u3400" <= char <= "\u9fff"
        for char in text
    )


def _remove_cjk_spaces(text: str) -> str:
    cjk = r"\u3040-\u30ff\u3400-\u9fff"
    return re.sub(rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", text)


def _normalize_cyrillic_candidate(text: str) -> str:
    latin_to_cyrillic = str.maketrans(
        {
            "A": "А", "a": "а", "B": "В", "b": "в",
            "C": "С", "c": "с", "E": "Е", "e": "е",
            "H": "Н", "h": "н", "K": "К", "k": "к",
            "M": "М", "m": "м", "N": "Н", "n": "н",
            "O": "О", "o": "о", "P": "Р", "p": "р",
            "T": "Т", "t": "т", "X": "Х", "x": "х",
            "Y": "У", "y": "у",
        }
    )
    return text.translate(latin_to_cyrillic)


def _clean_name(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s*[+*†‡]+\s*$", "", text)
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text, flags=re.UNICODE)
    return " ".join(text.split())[:40]


def _clean_reward_name(text: str) -> str:
    text = " ".join(text.strip().split())
    text = re.sub(r"\s+\(", "(", text)
    text = re.sub(r"^[^\w]+|[^\w)\]}]+$", "", text, flags=re.UNICODE)
    tokens = text.split()
    while tokens and not any(character.isalpha() for character in tokens[0]):
        tokens.pop(0)
    while tokens and not any(character.isalpha() for character in tokens[-1]):
        tokens.pop()
    return " ".join(tokens)[:160]


def _extract_bm(text: str) -> int | None:
    digits = "".join(char for char in text if char.isdigit())
    if not 5 <= len(digits) <= 9:
        return None
    value = int(digits)
    return value if 10_000 <= value <= 999_999_999 else None


def _get_rapid_engine(language: LangRec) -> RapidOCR:
    with _rapid_engine_lock:
        existing = _rapid_engines.get(language)
        if existing is not None:
            return existing

        params: dict[str, object] = {
            "Global.log_level": "ERROR",
            "Global.use_det": False,
            "Global.use_cls": False,
            "Rec.lang_type": language,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        }
        root = _resource_root()
        local_model_directories = (
            root / "rapidocr_models",
            root / "vendor" / "RapidOCR-models",
        )
        for local_models in local_model_directories:
            if local_models.exists():
                params["Global.model_root_dir"] = str(local_models)
                break
        engine = RapidOCR(params=params)
        _rapid_engines[language] = engine
        return engine


def _get_reward_rapid_engine() -> RapidOCR:
    """Return an OCR engine that detects Russian text anywhere in an image."""

    global _reward_rapid_engine
    with _rapid_engine_lock:
        if _reward_rapid_engine is not None:
            return _reward_rapid_engine

        params: dict[str, object] = {
            "Global.log_level": "ERROR",
            "Global.use_det": True,
            "Global.use_cls": False,
            "Rec.lang_type": LangRec.CYRILLIC,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        }
        root = _resource_root()
        local_model_directories = (
            root / "rapidocr_models",
            root / "vendor" / "RapidOCR-models",
        )
        for local_models in local_model_directories:
            if local_models.exists():
                params["Global.model_root_dir"] = str(local_models)
                break
        _reward_rapid_engine = RapidOCR(params=params)
        return _reward_rapid_engine


def _resource_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else Path(__file__).resolve().parent


def _tesseract_paths() -> tuple[Path, Path]:
    root = _resource_root()
    directories = (
        (root / "tesseract", root / "tesseract" / "tessdata_best"),
        (
            root / "vendor" / "Tesseract-OCR",
            root / "vendor" / "Tesseract-OCR" / "tessdata_best",
        ),
        (root / "tesseract", root / "tesseract" / "tessdata"),
        (
            root / "vendor" / "Tesseract-OCR",
            root / "vendor" / "Tesseract-OCR" / "tessdata",
        ),
    )
    for executable_directory, tessdata in directories:
        executable = executable_directory / "tesseract.exe"
        if executable.exists() and tessdata.exists():
            return executable, tessdata

    executable_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        executable = Path(folder) / executable_name
        tessdata = executable.parent / "tessdata"
        if executable.exists() and tessdata.exists():
            return executable, tessdata
    raise OcrError("OCR-компонент не найден.")


def _run_tesseract(
    image: Image.Image,
    languages: str,
    *,
    digit_only: bool = False,
    page_segmentation_mode: int = 12,
) -> str:
    executable, tessdata = _tesseract_paths()
    with tempfile.TemporaryDirectory(prefix="wheel-ocr-") as folder:
        image_path = Path(folder) / "atlas.png"
        image.save(image_path, format="PNG")
        command = [
            str(executable),
            str(image_path),
            "stdout",
            "--tessdata-dir",
            str(tessdata),
            "-l",
            languages,
            "--oem",
            "1",
            "--psm",
            str(page_segmentation_mode),
            "-c",
            "tessedit_create_tsv=1",
        ]
        if digit_only:
            command.extend(
                ["-c", "tessedit_char_whitelist=0123456789"]
            )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=90,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise OcrError("Не удалось запустить распознавание.") from error
        if result.returncode != 0:
            details = result.stderr.decode("utf-8", errors="replace").strip()
            raise OcrError(details or "Ошибка распознавания изображения.")
        return result.stdout.decode("utf-8", errors="replace")


def _parse_tsv_lines(tsv: str) -> list[OcrLine]:
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for word in reader:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        key = (
            word.get("page_num", ""),
            word.get("block_num", ""),
            word.get("par_num", ""),
            word.get("line_num", ""),
        )
        groups.setdefault(key, []).append(word)

    lines: list[OcrLine] = []
    for words in groups.values():
        words.sort(key=lambda item: int(item.get("left", "0") or 0))
        left = min(int(item.get("left", "0") or 0) for item in words)
        top = min(int(item.get("top", "0") or 0) for item in words)
        right = max(
            int(item.get("left", "0") or 0)
            + int(item.get("width", "0") or 0)
            for item in words
        )
        bottom = max(
            int(item.get("top", "0") or 0)
            + int(item.get("height", "0") or 0)
            for item in words
        )
        confidences: list[float] = []
        for item in words:
            try:
                confidence = float(item.get("conf", "-1") or -1)
            except ValueError:
                confidence = -1
            if confidence >= 0:
                confidences.append(confidence)
        lines.append(
            OcrLine(
                text=" ".join((item.get("text") or "").strip() for item in words),
                left=left,
                top=top,
                width=right - left,
                height=max(1, bottom - top),
                confidence=(
                    sum(confidences) / len(confidences) if confidences else 0.0
                ),
            )
        )
    return sorted(lines, key=lambda line: (line.top, line.left))
