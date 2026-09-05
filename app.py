from __future__ import annotations

import calendar
import json
import math
import os
import queue
import random
import secrets
import sys
import threading
import time
import tempfile
import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import (
    Image,
    ImageChops,
    ImageColor,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageTk,
)
from ocr_import import (
    OcrError,
    RecognizedParticipant,
    clipboard_image,
    recognize_participants,
    recognize_reward_name,
)


APP_NAME = "SYNDICATE"
BACKGROUND = "#121513"
PANEL_BACKGROUND = "#191D1A"
SURFACE = "#202521"
SURFACE_LIGHT = "#292E2A"
INPUT_BACKGROUND = "#151916"
BORDER = "#464C47"
BORDER_LIGHT = "#858D87"
TEXT = "#D5D9D5"
TEXT_BRIGHT = "#E0E3E0"
MUTED = "#929992"
DISABLED_TEXT = "#626862"
ACCENT = "#A78C4D"
ACCENT_HOVER = "#C0A663"
ACCENT_DARK = "#6F6038"
BRAND_GREEN = "#75877D"
BRAND_GREEN_LIGHT = "#9EACA4"
DANGER = "#8B4646"
SUCCESS = "#587461"
BUTTON_HOVER = "#343A35"
BUTTON_BORDER = "#4A514B"
BUTTON_HOVER_BORDER = "#777F79"
ROW_HOVER = "#2A302B"
ROW_SELECTED = "#272E29"
ROW_SELECTED_HOVER = "#2D352F"
CTA_BACKGROUND = "#8D7841"
CTA_BORDER = "#B69A57"
CTA_HOVER = "#A18A4C"
CTA_HOVER_BORDER = "#D0B873"
CTA_PRESSED = "#756333"
CTA_DISABLED = "#353936"
DEFAULT_BM_INFLUENCE_PERCENT = 100.0
WHEEL_COLORS = (
    "#242B27",
    "#303832",
    "#3B433D",
    "#465149",
)
WINNER_SECTOR = "#514D37"
WHEEL_SEPARATOR = "#707871"
WHEEL_METAL = "#727A74"
WHEEL_METAL_LIGHT = "#B1B7B2"
WHEEL_METAL_DARK = "#292E2A"
WHEEL_METAL_SHADOW = "#080A09"
WINNER_BACKGROUND = "#1B1F1C"
DESIGN_SCREEN_WIDTH = 1920
DESIGN_SCREEN_HEIGHT = 1080
MIN_UI_SCALE = 0.55
MAX_UI_SCALE = 2.0


def encode_mp4_frames(
    frames: Iterable[Image.Image],
    frame_size: tuple[int, int],
    fps: float,
) -> bytes:
    """Encode RGB Pillow frames to a self-contained MP4 byte stream."""

    width, height = frame_size
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("MP4 frame dimensions must be positive and even")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("MP4 frame rate must be positive")

    handle, temporary_name = tempfile.mkstemp(
        prefix="syndicate-roll-",
        suffix=".mp4",
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    writer: cv2.VideoWriter | None = None
    try:
        temporary_path.unlink(missing_ok=True)
        candidates: list[tuple[int, str]] = []
        if os.name == "nt":
            candidates.extend(
                (
                    (cv2.CAP_MSMF, "avc1"),
                    (cv2.CAP_MSMF, "H264"),
                )
            )
        candidates.append((cv2.CAP_FFMPEG, "mp4v"))

        for backend, codec in candidates:
            candidate = cv2.VideoWriter(
                str(temporary_path),
                backend,
                cv2.VideoWriter_fourcc(*codec),
                fps,
                (width, height),
            )
            if candidate.isOpened():
                writer = candidate
                break
            candidate.release()
            temporary_path.unlink(missing_ok=True)
        if writer is None:
            raise RuntimeError("На этом устройстве не найден кодек для MP4")

        frame_count = 0
        for frame in frames:
            if not isinstance(frame, Image.Image):
                raise TypeError("MP4 frames must be Pillow images")
            rgb_frame = frame.convert("RGB")
            if rgb_frame.size != (width, height):
                raise ValueError("Every MP4 frame must have the same size")
            bgr_frame = cv2.cvtColor(np.asarray(rgb_frame), cv2.COLOR_RGB2BGR)
            writer.write(bgr_frame)
            frame_count += 1
        writer.release()
        writer = None
        if frame_count == 0:
            raise ValueError("At least one MP4 frame is required")
        payload = temporary_path.read_bytes()
        if len(payload) < 256 or b"ftyp" not in payload[:64]:
            raise RuntimeError("Видеокодек создал повреждённый MP4")
        return payload
    finally:
        if writer is not None:
            writer.release()
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def resource_path(*parts: str) -> Path:
    """Resolve a resource both from source and from a PyInstaller bundle."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    base = Path(bundle_root) if bundle_root else Path(__file__).resolve().parent
    return base.joinpath(*parts)


def application_directory() -> Path:
    """Return the folder containing app.py or the packaged executable."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def widget_ui_scale(widget: tk.Misc) -> float:
    try:
        return float(getattr(widget.winfo_toplevel(), "ui_scale", 1.0))
    except (AttributeError, tk.TclError, TypeError, ValueError):
        return 1.0


def scaled_px(widget: tk.Misc, value: float, minimum: int = 1) -> int:
    return max(minimum, round(value * widget_ui_scale(widget)))


def monitor_size_for_window(window: tk.Misc) -> tuple[int, int]:
    """Return the pixel size of the monitor containing a Tk window."""

    if os.name != "nt":
        return window.winfo_screenwidth(), window.winfo_screenheight()
    try:
        from ctypes import (
            POINTER,
            Structure,
            byref,
            c_int,
            c_ulong,
            c_void_p,
            sizeof,
            windll,
        )
        from ctypes.wintypes import RECT

        class MonitorInfo(Structure):
            _fields_ = (
                ("cbSize", c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", c_ulong),
            )

        window.update_idletasks()
        windll.user32.GetParent.argtypes = (c_void_p,)
        windll.user32.GetParent.restype = c_void_p
        windll.user32.MonitorFromWindow.argtypes = (c_void_p, c_ulong)
        windll.user32.MonitorFromWindow.restype = c_void_p
        windll.user32.GetMonitorInfoW.argtypes = (
            c_void_p,
            POINTER(MonitorInfo),
        )
        windll.user32.GetMonitorInfoW.restype = c_int
        client_handle = window.winfo_id()
        native_handle = windll.user32.GetParent(client_handle) or client_handle
        monitor = windll.user32.MonitorFromWindow(c_void_p(native_handle), 2)
        if not monitor:
            raise OSError("MonitorFromWindow failed")
        info = MonitorInfo()
        info.cbSize = sizeof(MonitorInfo)
        if not windll.user32.GetMonitorInfoW(c_void_p(monitor), byref(info)):
            raise OSError("GetMonitorInfoW failed")
        return (
            int(info.rcMonitor.right - info.rcMonitor.left),
            int(info.rcMonitor.bottom - info.rcMonitor.top),
        )
    except (AttributeError, OSError, tk.TclError, TypeError, ValueError):
        return window.winfo_screenwidth(), window.winfo_screenheight()


def apply_window_icon(window: tk.Misc, default: bool = False) -> None:
    """Apply the guild emblem to Tk windows and the Windows taskbar."""

    try:
        window.iconbitmap(str(resource_path("imgs", "guild app icon.ico")))
    except (OSError, tk.TclError):
        pass
    try:
        with Image.open(resource_path("imgs", "guild app icon.png")) as source:
            icon = source.convert("RGBA")
        icon.thumbnail((256, 256), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(icon)
        window.iconphoto(default, photo)
        window._guild_icon_photo = photo  # type: ignore[attr-defined]
    except (OSError, ValueError, tk.TclError):
        pass


def apply_dark_title_bar(window: tk.Misc) -> None:
    """Apply a native dark Windows caption without replacing window controls."""

    if os.name != "nt":
        return
    try:
        from ctypes import byref, c_int, c_uint, c_void_p, sizeof, windll

        window.update_idletasks()
        windll.user32.GetParent.argtypes = (c_void_p,)
        windll.user32.GetParent.restype = c_void_p
        windll.dwmapi.DwmSetWindowAttribute.argtypes = (
            c_void_p,
            c_uint,
            c_void_p,
            c_uint,
        )
        windll.dwmapi.DwmSetWindowAttribute.restype = c_int
        windll.user32.SetWindowPos.argtypes = (
            c_void_p,
            c_void_p,
            c_int,
            c_int,
            c_int,
            c_int,
            c_uint,
        )
        client_handle = window.winfo_id()
        window_handle = windll.user32.GetParent(client_handle) or client_handle

        enabled = c_int(1)
        for attribute in (20, 19):
            result = windll.dwmapi.DwmSetWindowAttribute(
                window_handle,
                attribute,
                byref(enabled),
                sizeof(enabled),
            )
            if result == 0:
                break

        # Exact per-window caption colors are available only on Windows 11.
        # Windows 10 keeps the native immersive dark caption enabled above.
        if sys.getwindowsversion().build >= 22000:
            def colorref(hex_color: str) -> c_int:
                red, green, blue = ImageColor.getrgb(hex_color)
                return c_int(red | (green << 8) | (blue << 16))

            for attribute, color in (
                (35, BACKGROUND),
                (36, "#D9DDD9"),
                (34, "#383E39"),
            ):
                value = colorref(color)
                windll.dwmapi.DwmSetWindowAttribute(
                    window_handle,
                    attribute,
                    byref(value),
                    sizeof(value),
                )

        # Ask Windows to redraw the non-client area immediately.
        windll.user32.SetWindowPos(
            window_handle,
            0,
            0,
            0,
            0,
            0,
            0x0020 | 0x0001 | 0x0002 | 0x0004,
        )
    except (AttributeError, OSError, tk.TclError):
        pass


def keep_dark_title_bar(window: tk.Misc) -> None:
    """Reapply DWM caption styling after Windows remaps a native window."""

    if os.name != "nt":
        return

    pending: set[str] = set()
    state = {"destroyed": False, "refreshing": False}

    def apply_if_alive() -> None:
        if state["destroyed"] or state["refreshing"]:
            return
        try:
            if not window.winfo_exists():
                return
            state["refreshing"] = True
            apply_dark_title_bar(window)
        except tk.TclError:
            pass
        finally:
            state["refreshing"] = False

    def schedule(delay_ms: int) -> None:
        token_box: dict[str, str] = {}

        def run() -> None:
            token = token_box.get("token")
            if token is not None:
                pending.discard(token)
            apply_if_alive()

        try:
            token = window.after(delay_ms, run)
        except tk.TclError:
            return
        token_box["token"] = token
        pending.add(token)

    def refresh(event: tk.Event[tk.Misc]) -> None:
        if event.widget is not window or state["destroyed"]:
            return
        apply_if_alive()
        # DWM can finish rebuilding a restored caption after Tk's Map event.
        # Two short retries cover both the immediate and delayed restore paths.
        schedule(20)
        schedule(120)

    def cleanup(event: tk.Event[tk.Misc]) -> None:
        if event.widget is not window:
            return
        state["destroyed"] = True
        for token in tuple(pending):
            try:
                window.after_cancel(token)
            except tk.TclError:
                pass
        pending.clear()

    window.bind("<Map>", refresh, add="+")
    window.bind("<Destroy>", cleanup, add="+")


def clipboard_sequence_number() -> int:
    """Return the Windows clipboard revision without opening the clipboard."""

    if os.name != "nt":
        return 0
    try:
        from ctypes import windll

        return int(windll.user32.GetClipboardSequenceNumber())
    except (AttributeError, OSError):
        return 0


def handle_entry_shortcut(event: tk.Event[tk.Misc]) -> str | None:
    """Provide layout-independent Windows editing shortcuts for text fields."""

    entry = event.widget
    if not isinstance(entry, (tk.Entry, ttk.Entry)):
        return None

    keycode = int(getattr(event, "keycode", 0) or 0)
    keysym = str(getattr(event, "keysym", "")).casefold()
    actions = {
        "select_all": keycode == 65
        or keysym in {"a", "ф", "cyrillic_ef"},
        "copy": keycode == 67
        or keysym in {"c", "с", "cyrillic_es"},
        "paste": keycode == 86
        or keysym in {"v", "м", "cyrillic_em"},
        "cut": keycode == 88
        or keysym in {"x", "ч", "cyrillic_che"},
    }
    action = next((name for name, active in actions.items() if active), None)
    if action is None:
        return None

    editable = str(entry.cget("state")) == "normal"
    if action == "select_all":
        entry.selection_range(0, tk.END)
        entry.icursor(tk.END)
        return "break"

    try:
        selection_start = entry.index(tk.SEL_FIRST)
        selection_end = entry.index(tk.SEL_LAST)
    except tk.TclError:
        selection_start = selection_end = None

    if action in {"copy", "cut"}:
        if selection_start is not None and selection_end is not None:
            selected_text = entry.get()[selection_start:selection_end]
            entry.clipboard_clear()
            entry.clipboard_append(selected_text)
            if action == "cut" and editable:
                entry.delete(selection_start, selection_end)
        return "break"

    if not editable:
        return "break"
    try:
        clipboard_text = entry.clipboard_get()
    except tk.TclError:
        return "break"
    # Entry is single-line; normalize multiline clipboard content accordingly.
    clipboard_text = " ".join(str(clipboard_text).splitlines())
    if selection_start is not None and selection_end is not None:
        entry.delete(selection_start, selection_end)
    entry.insert(tk.INSERT, clipboard_text)
    return "break"


def enable_entry_shortcuts(entry: tk.Entry | ttk.Entry) -> None:
    entry.bind("<Control-KeyPress>", handle_entry_shortcut, add="+")


def is_foreground_window(window: tk.Misc) -> bool:
    """Check whether a Tk top-level currently owns the foreground."""

    if os.name != "nt":
        return window.focus_displayof() is not None
    try:
        from ctypes import c_void_p, windll

        windll.user32.GetParent.argtypes = (c_void_p,)
        windll.user32.GetParent.restype = c_void_p
        windll.user32.GetForegroundWindow.restype = c_void_p
        client_handle = window.winfo_id()
        window_handle = windll.user32.GetParent(client_handle) or client_handle
        return int(windll.user32.GetForegroundWindow() or 0) == int(
            window_handle
        )
    except (AttributeError, OSError, tk.TclError):
        return False


@dataclass
class Participant:
    name: str
    enabled: bool = True
    bm: float = 0.0


@dataclass(frozen=True)
class NicknameCorrection:
    recognized: str
    replacement: str


@dataclass(frozen=True)
class DrawResult:
    winner: str
    reward: str
    timestamp: str


@dataclass(frozen=True)
class RecordedWheelFrame:
    rotation: float
    names: tuple[str, ...]
    probabilities: tuple[float, ...]
    winner_index: int | None = None


def clean_nickname(name: str) -> str:
    return " ".join(name.strip().split())


def nickname_lookup_key(name: str) -> str:
    return clean_nickname(name).casefold()


def format_bm(value: float) -> str:
    """Format BM for quick visual scanning while keeping decimals if present."""

    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    whole, fraction = f"{value:.2f}".rstrip("0").rstrip(".").split(".")
    return f"{int(whole):,}".replace(",", " ") + f".{fraction}"


def format_draw_timestamp(value: str) -> str:
    """Format an ISO draw timestamp without changing its recorded wall time."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return value
    return parsed.strftime("%d.%m.%Y %H:%M")


def draw_result_date(value: str) -> date | None:
    """Return the recorded local calendar date from an ISO timestamp."""

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (AttributeError, TypeError, ValueError):
        return None


def parse_bm(value: str) -> float:
    """Parse both plain and visually grouped BM values."""

    compact = value.replace("\u00a0", "").replace(" ", "").strip()
    return float(compact.replace(",", ".") or "0")


def sort_participants_by_bm(
    participants: list[Participant],
) -> list[Participant]:
    """Return participants ordered by BM from highest to lowest."""

    return sorted(participants, key=lambda participant: participant.bm, reverse=True)


class AnimatedEllipsis:
    """Animate trailing dots on a button while a background task is active."""

    INTERVAL_MS = 320
    DOT_SLOTS = 3
    PUNCTUATION_SPACE = "\u2008"

    def __init__(self, owner: tk.Misc) -> None:
        self.owner = owner
        self.widget: tk.Widget | None = None
        self.base_text = ""
        self.phase = 0
        self.after_id: str | None = None

    def start(self, widget: tk.Widget, base_text: str) -> None:
        self.stop()
        self.widget = widget
        self.base_text = base_text.rstrip(". …")
        self.phase = 0
        self._tick()

    def stop(self) -> None:
        if self.after_id is not None:
            try:
                self.owner.after_cancel(self.after_id)
            except tk.TclError:
                pass
        self.after_id = None
        self.widget = None

    def _tick(self) -> None:
        widget = self.widget
        if widget is None:
            return
        try:
            if not widget.winfo_exists():
                self.stop()
                return
            visible_dots = "." * self.phase
            reserved_dots = self.PUNCTUATION_SPACE * (
                self.DOT_SLOTS - self.phase
            )
            widget.configure(
                text=self.base_text + visible_dots + reserved_dots
            )
        except tk.TclError:
            self.stop()
            return
        self.phase = (self.phase + 1) % (self.DOT_SLOTS + 1)
        self.after_id = self.owner.after(self.INTERVAL_MS, self._tick)


def participant_weights(
    participants: list[Participant],
    influence_percent: float = DEFAULT_BM_INFLUENCE_PERCENT,
    normalization_population: list[Participant] | None = None,
) -> list[float]:
    """Split probability into equal and normalized-BM pools.

    BM values are min-max normalized against the whole supplied population,
    while the BM probability pool is shared only by the draw participants.
    """
    if not participants:
        return []

    population = normalization_population or participants
    population_values = [max(0.0, participant.bm) for participant in population]
    minimum = min(population_values)
    maximum = max(population_values)
    spread = maximum - minimum
    influence = (
        min(100.0, max(0.0, influence_percent)) / 100.0
        if math.isfinite(influence_percent)
        else 0.0
    )
    participant_count = len(participants)

    if math.isclose(spread, 0.0):
        normalized_values = [0.0] * participant_count
    else:
        normalized_values = [
            min(
                1.0,
                max(0.0, (max(0.0, participant.bm) - minimum) / spread),
            )
            for participant in participants
        ]

    normalized_total = sum(normalized_values)
    if math.isclose(normalized_total, 0.0):
        return [1.0 / participant_count] * participant_count

    equal_share = (1.0 - influence) / participant_count
    return [
        equal_share + influence * normalized / normalized_total
        for normalized in normalized_values
    ]


def participant_probabilities(
    participants: list[Participant],
    influence_percent: float = DEFAULT_BM_INFLUENCE_PERCENT,
    normalization_population: list[Participant] | None = None,
) -> list[float]:
    weights = participant_weights(
        participants, influence_percent, normalization_population
    )
    total = sum(weights)
    return [weight / total for weight in weights] if total else []


def weighted_random_index(weights: list[float]) -> int:
    """Choose an index using OS-provided randomness and the supplied weights."""
    if not weights or any(weight < 0 for weight in weights):
        raise ValueError("Weights must be non-negative")
    total = sum(weights)
    if total <= 0:
        raise ValueError("At least one weight must be positive")
    threshold = (secrets.randbits(53) / (1 << 53)) * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if threshold < cumulative:
            return index
    return len(weights) - 1


class ParticipantStore:
    """Store portable user data beside the source or packaged executable."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = application_directory() / "data.json"
        self.path = path
        self.bm_influence_percent = DEFAULT_BM_INFLUENCE_PERCENT
        self.nickname_corrections: list[NicknameCorrection] = []

    def load(self) -> list[Participant]:
        if not self.path.exists():
            self.save([])
            return []

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            influence = float(
                raw.get("bm_influence_percent", DEFAULT_BM_INFLUENCE_PERCENT)
            )
            if not math.isfinite(influence):
                influence = DEFAULT_BM_INFLUENCE_PERCENT
            self.bm_influence_percent = min(100.0, max(0.0, influence))
            corrections: dict[str, NicknameCorrection] = {}
            raw_corrections = raw.get("nickname_corrections", [])
            if isinstance(raw_corrections, dict):
                raw_corrections = [
                    {"recognized": recognized, "replacement": replacement}
                    for recognized, replacement in raw_corrections.items()
                ]
            if isinstance(raw_corrections, list):
                for item in raw_corrections:
                    if not isinstance(item, dict):
                        continue
                    recognized = clean_nickname(str(item.get("recognized", "")))
                    replacement = clean_nickname(str(item.get("replacement", "")))
                    key = nickname_lookup_key(recognized)
                    if key and replacement:
                        corrections[key] = NicknameCorrection(
                            recognized, replacement
                        )
            self.nickname_corrections = list(corrections.values())
            items = raw.get("participants", [])
            result = [
                Participant(
                    str(item["name"]).strip(),
                    False,
                    max(0.0, float(item.get("bm", 0.0))),
                )
                for item in items
                if str(item.get("name", "")).strip()
            ]
            return result
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def save(
        self,
        participants: list[Participant],
        bm_influence_percent: float | None = None,
        nickname_corrections: list[NicknameCorrection] | None = None,
    ) -> None:
        influence = self.bm_influence_percent
        if bm_influence_percent is not None:
            influence = min(100.0, max(0.0, bm_influence_percent))
        corrections = (
            list(nickname_corrections)
            if nickname_corrections is not None
            else list(self.nickname_corrections)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bm_influence_percent": influence,
            "participants": [
                {"name": item.name, "bm": item.bm} for item in participants
            ],
            "nickname_corrections": [
                {
                    "recognized": correction.recognized,
                    "replacement": correction.replacement,
                }
                for correction in corrections
            ],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
        self.bm_influence_percent = influence
        self.nickname_corrections = corrections


class DrawLogStore:
    """Keep confirmed draw results in a portable JSON file beside the app."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or application_directory() / "draw_log.json"

    def load(self) -> list[DrawResult]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("draws", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            raise ValueError("Некорректный формат журнала розыгрышей.")

        results: list[DrawResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            winner = str(item.get("winner", "")).strip()
            reward = str(item.get("reward", "")).strip()
            timestamp = str(item.get("timestamp", "")).strip()
            if winner and reward and timestamp:
                results.append(DrawResult(winner, reward, timestamp))
        return results

    def append(self, result: DrawResult) -> None:
        self.append_many([result])

    def append_many(self, new_results: list[DrawResult]) -> None:
        if not new_results:
            return
        results = self.load()
        results.extend(new_results)
        self._write(results)

    def remove_at(self, index: int) -> DrawResult:
        results = self.load()
        if not 0 <= index < len(results):
            raise IndexError("Запись розыгрыша не найдена.")
        removed = results.pop(index)
        self._write(results)
        return removed

    def _write(self, results: list[DrawResult]) -> None:
        payload = {
            "version": 1,
            "draws": [
                {
                    "winner": item.winner,
                    "reward": item.reward,
                    "timestamp": item.timestamp,
                }
                for item in results
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class StyledCheckbutton(tk.Canvas):
    SIZE = 30

    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.BooleanVar,
        background: str = SURFACE,
    ) -> None:
        self.ui_scale = widget_ui_scale(parent)
        self.size = max(16, round(self.SIZE * self.ui_scale))
        super().__init__(
            parent,
            width=self.size,
            height=self.size,
            bg=background,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.variable = variable
        self.hovered = False
        self._trace_id = variable.trace_add("write", self._on_value_changed)
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._redraw)
        self.bind("<FocusOut>", self._redraw)
        self.bind("<Destroy>", self._remove_trace, add="+")
        self._redraw()

    def _toggle(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if str(self.cget("state")) != "disabled":
            self.variable.set(not self.variable.get())
        return "break"

    def _on_value_changed(self, *_args: object) -> None:
        self._redraw()

    def _enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        px = lambda value: max(1, round(value * self.ui_scale))
        self.delete("all")
        selected = self.variable.get()
        focused = self.focus_get() is self
        if selected:
            fill = BRAND_GREEN
            outline = "#A4ACA6" if self.hovered or focused else BRAND_GREEN_LIGHT
        else:
            fill = "#202521" if self.hovered else "#171A18"
            outline = "#A4ACA6" if self.hovered or focused else "#626A64"
        self.create_rectangle(
            px(3),
            px(3),
            self.size - px(3),
            self.size - px(3),
            fill=fill,
            outline=outline,
            width=px(2),
        )
        if selected:
            self.create_line(
                px(8),
                px(15),
                px(13),
                px(20),
                px(22),
                px(10),
                fill="#E3E6E3",
                width=px(3),
                capstyle="round",
                joinstyle="round",
            )

    def _remove_trace(self, _event: tk.Event[tk.Misc]) -> None:
        try:
            self.variable.trace_remove("write", self._trace_id)
        except tk.TclError:
            pass


class StyledDeleteButton(tk.Canvas):
    SIZE = 30

    def __init__(
        self,
        parent: tk.Misc,
        command: object,
        background: str = SURFACE,
    ) -> None:
        self.ui_scale = widget_ui_scale(parent)
        self.size = max(16, round(self.SIZE * self.ui_scale))
        super().__init__(
            parent,
            width=self.size,
            height=self.size,
            bg=background,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.base_background = background
        self.command = command
        self.hovered = False
        self.bind("<Button-1>", self._activate)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._redraw)
        self.bind("<FocusOut>", self._redraw)
        self._redraw()

    def _activate(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if str(self.cget("state")) != "disabled" and callable(self.command):
            self.command()
        return "break"

    def _enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        px = lambda value: max(1, round(value * self.ui_scale))
        self.delete("all")
        focused = self.focus_get() is self
        active = self.hovered or focused
        fill = "#302424" if active else self.base_background
        outline = "#60403E" if active else self.base_background
        cross = "#A87872" if active else "#656B66"
        self.create_rectangle(
            px(3),
            px(3),
            self.size - px(3),
            self.size - px(3),
            fill=fill,
            outline=outline,
            width=px(1),
        )
        cross_width = px(2 if active else 1)
        self.create_line(
            px(10),
            px(10),
            px(20),
            px(20),
            fill=cross,
            width=cross_width,
            capstyle="round",
        )
        self.create_line(
            px(20),
            px(10),
            px(10),
            px(20),
            fill=cross,
            width=cross_width,
            capstyle="round",
        )


class PrizeImageCard(tk.Canvas):
    EMPTY_WIDTH = 180
    EMPTY_HEIGHT = 56
    BORDER_PADDING = 2
    MAX_CARD_WIDTH = 500
    MAX_IMAGE_WIDTH = MAX_CARD_WIDTH - BORDER_PADDING * 2
    MAX_IMAGE_HEIGHT = 64

    def __init__(
        self,
        parent: tk.Misc,
        max_card_width: int | None = None,
        on_clear: Callable[[], None] | None = None,
    ) -> None:
        self.ui_scale = widget_ui_scale(parent)
        logical_max_width = max_card_width or self.MAX_CARD_WIDTH
        self.max_image_width = logical_max_width - self.BORDER_PADDING * 2
        self.on_clear = on_clear
        self.empty_width = max(90, round(self.EMPTY_WIDTH * self.ui_scale))
        self.empty_height = max(32, round(self.EMPTY_HEIGHT * self.ui_scale))
        self.border_padding = max(1, round(self.BORDER_PADDING * self.ui_scale))
        super().__init__(
            parent,
            width=self.empty_width,
            height=self.empty_height,
            bg=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.image: Image.Image | None = None
        self.normal_photo: ImageTk.PhotoImage | None = None
        self.dimmed_photo: ImageTk.PhotoImage | None = None
        self.hovered = False
        self.card_width = self.empty_width
        self.card_height = self.empty_height
        self.locked = False
        self.bind("<Button-1>", self._activate)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._redraw)
        self.bind("<FocusOut>", self._redraw)
        self._redraw()

    def _activate(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self.locked:
            return "break"
        if self.image is not None:
            self.clear()
            return "break"
        try:
            image = clipboard_image()
        except OcrError as error:
            messagebox.showwarning(
                APP_NAME,
                str(error),
                parent=self.winfo_toplevel(),
            )
            return "break"
        self.set_image(image)
        return "break"

    def set_image(self, image: Image.Image) -> None:
        self.image = image.copy()
        source = self.image.convert("RGBA")
        source.thumbnail(
            (self.max_image_width, self.MAX_IMAGE_HEIGHT),
            Image.Resampling.LANCZOS,
        )
        if not math.isclose(self.ui_scale, 1.0):
            source = source.resize(
                (
                    max(1, round(source.width * self.ui_scale)),
                    max(1, round(source.height * self.ui_scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        preview = Image.new(
            "RGBA",
            source.size,
            ImageColor.getrgb(SURFACE) + (255,),
        )
        preview.alpha_composite(source, (0, 0))
        normal = preview.convert("RGB")
        dim_layer = Image.new("RGB", normal.size, WINNER_BACKGROUND)
        dimmed = Image.blend(normal, dim_layer, 0.58)
        self.normal_photo = ImageTk.PhotoImage(normal)
        self.dimmed_photo = ImageTk.PhotoImage(dimmed)
        self.card_width = source.width + self.border_padding * 2
        self.card_height = source.height + self.border_padding * 2
        self.configure(width=self.card_width, height=self.card_height)
        self._redraw()

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        self.configure(cursor="arrow" if locked else "hand2")

    def clear(self) -> None:
        self.image = None
        self.normal_photo = None
        self.dimmed_photo = None
        self.card_width = self.empty_width
        self.card_height = self.empty_height
        self.configure(width=self.card_width, height=self.card_height)
        self._redraw()
        if self.on_clear is not None:
            self.on_clear()

    def _enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        px = lambda value: max(1, round(value * self.ui_scale))
        self.delete("all")
        focused = self.focus_get() is self
        center_x = self.card_width // 2
        center_y = self.card_height // 2
        border = BORDER_LIGHT if self.hovered or focused else BORDER

        self.create_rectangle(
            px(1),
            px(1),
            self.card_width - px(1),
            self.card_height - px(1),
            fill=SURFACE,
            outline=border,
            width=px(2),
        )
        if self.image is None:
            plus_color = ACCENT_HOVER if self.hovered or focused else MUTED
            self.create_line(
                center_x - px(13),
                center_y,
                center_x + px(13),
                center_y,
                fill=plus_color,
                width=px(3),
                capstyle="round",
            )
            self.create_line(
                center_x,
                center_y - px(13),
                center_x,
                center_y + px(13),
                fill=plus_color,
                width=px(3),
                capstyle="round",
            )
            return

        photo = self.dimmed_photo if self.hovered else self.normal_photo
        if photo is not None:
            self.create_image(center_x, center_y, image=photo)
        self.create_rectangle(
            px(1),
            px(1),
            self.card_width - px(1),
            self.card_height - px(1),
            outline=border,
            width=px(2),
        )
        if self.hovered or focused:
            cross_size = min(
                px(14),
                max(px(7), min(self.card_width, self.card_height) // 4),
            )
            self.create_line(
                center_x - cross_size,
                center_y - cross_size,
                center_x + cross_size,
                center_y + cross_size,
                fill=TEXT_BRIGHT,
                width=px(4),
                capstyle="round",
            )
            self.create_line(
                center_x + cross_size,
                center_y - cross_size,
                center_x - cross_size,
                center_y + cross_size,
                fill=TEXT_BRIGHT,
                width=px(4),
                capstyle="round",
            )


class PrizeQuantityControl(tk.Frame):
    MINIMUM = 1
    MAXIMUM = 9999

    def __init__(self, parent: tk.Misc, value: int = 1) -> None:
        super().__init__(parent, bg=BACKGROUND)
        self.ui_scale = widget_ui_scale(parent)
        self.control_size = max(18, round(30 * self.ui_scale))
        self.locked = False
        self.quantity_var = tk.StringVar(value=str(value))
        validator = (self.register(self._validate), "%P")

        self.minus_button = self._step_button("−", -1)
        entry_slot = tk.Frame(
            self,
            width=self.control_size,
            height=self.control_size,
            bg=BACKGROUND,
        )
        entry_slot.pack(
            side="left",
            padx=max(1, round(3 * self.ui_scale)),
        )
        entry_slot.pack_propagate(False)
        self.entry = tk.Entry(
            entry_slot,
            textvariable=self.quantity_var,
            justify="center",
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=INPUT_BACKGROUND,
            disabledforeground=TEXT,
            relief="flat",
            font=("Segoe UI Semibold", 11),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER_LIGHT,
            validate="key",
            validatecommand=validator,
        )
        enable_entry_shortcuts(self.entry)
        self.entry.pack(fill="both", expand=True)
        self.plus_button = self._step_button("+", 1)
        self.multiply_label = tk.Label(
            self,
            text="X",
            bg=BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Light", 21),
        )
        self.multiply_label.pack(
            side="left",
            padx=(
                max(1, round(8 * self.ui_scale)),
                0,
            ),
        )

        self.entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")
        self.entry.bind("<Return>", self._commit_and_release_focus, add="+")
        self.entry.bind("<KP_Enter>", self._commit_and_release_focus, add="+")
        self.entry.bind("<Up>", lambda _event: self._adjust(1), add="+")
        self.entry.bind("<Down>", lambda _event: self._adjust(-1), add="+")
        self.set_value(value)

    def _step_button(self, text: str, delta: int) -> tk.Button:
        slot = tk.Frame(
            self,
            width=self.control_size,
            height=self.control_size,
            bg=BACKGROUND,
        )
        slot.pack(side="left")
        slot.pack_propagate(False)
        button = tk.Button(
            slot,
            text=text,
            command=lambda: self._adjust(delta),
            bg=SURFACE_LIGHT,
            fg=TEXT,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_BRIGHT,
            disabledforeground=DISABLED_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BUTTON_BORDER,
            highlightcolor=BUTTON_BORDER,
            cursor="hand2",
            font=("Segoe UI Semibold", 12),
            padx=0,
            pady=0,
        )
        button.pack(fill="both", expand=True)
        return button

    def _validate(self, proposed: str) -> bool:
        return proposed == "" or (
            proposed.isdigit() and len(proposed) <= len(str(self.MAXIMUM))
        )

    def value(self) -> int:
        try:
            value = int(self.quantity_var.get())
        except ValueError:
            value = self.MINIMUM
        value = min(self.MAXIMUM, max(self.MINIMUM, value))
        normalized = str(value)
        if self.quantity_var.get() != normalized:
            self.quantity_var.set(normalized)
        return value

    def set_value(self, value: int) -> None:
        normalized = min(self.MAXIMUM, max(self.MINIMUM, int(value)))
        self.quantity_var.set(str(normalized))

    def _adjust(self, delta: int) -> str:
        if not self.locked:
            self.set_value(self.value() + delta)
        return "break"

    def _on_focus_in(self, _event: tk.Event[tk.Misc]) -> None:
        self.entry.configure(
            highlightbackground=BORDER_LIGHT,
            highlightcolor=BORDER_LIGHT,
        )

    def _on_focus_out(self, _event: tk.Event[tk.Misc]) -> None:
        self.value()
        self.entry.configure(
            highlightbackground=BORDER,
            highlightcolor=BORDER_LIGHT,
        )

    def _commit_and_release_focus(
        self, _event: tk.Event[tk.Misc]
    ) -> str:
        self.value()
        self.winfo_toplevel().focus_set()
        return "break"

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        state = "disabled" if locked else "normal"
        cursor = "arrow" if locked else "hand2"
        self.entry.configure(state=state)
        self.minus_button.configure(state=state, cursor=cursor)
        self.plus_button.configure(state=state, cursor=cursor)


class NicknameCorrectionsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: "ScreenshotImportDialog",
        app: "WheelApp",
    ) -> None:
        super().__init__(parent)
        self.withdraw()
        self.ui_scale = float(getattr(parent, "ui_scale", 1.0))
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.parent_dialog = parent
        self.app = app
        self._scrollbar_visible = False
        self.title("Замены ников")
        apply_window_icon(self)
        self.geometry(f"{self._px(650)}x{self._px(470)}")
        self.minsize(self._px(560), self._px(360))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self._build_ui()
        self.after_idle(self._center_on_parent)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=PANEL_BACKGROUND)
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(20), self._px(12)),
        )
        tk.Label(
            header,
            text="ЗАМЕНЫ НИКОВ",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left")
        self.count_label = tk.Label(
            header,
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 12),
        )
        self.count_label.pack(
            side="left", padx=(self._px(8), 0), pady=(self._px(2), 0)
        )

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(fill="both", expand=True, padx=self._px(22))

        columns_header = tk.Frame(
            list_shell, bg=SURFACE, height=self._px(30)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        columns_header.grid_columnconfigure(0, weight=1, uniform="corrections")
        columns_header.grid_columnconfigure(1, weight=1, uniform="corrections")
        tk.Label(
            columns_header,
            text="РАСПОЗНАНО",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(self._px(18), 0),
            pady=(self._px(7), self._px(4)),
        )
        tk.Label(
            columns_header,
            text="ИСПОЛЬЗОВАТЬ",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(self._px(18), 0),
            pady=(self._px(7), self._px(4)),
        )
        tk.Frame(list_shell, bg="#343B36", height=self._px(1)).pack(fill="x")

        body = tk.Frame(list_shell, bg=SURFACE)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            body, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            body, orient="vertical", command=self.canvas.yview
        )
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_window = self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)

        footer = tk.Frame(self, bg=PANEL_BACKGROUND)
        footer.pack(
            fill="x", padx=self._px(22), pady=self._px(18)
        )
        ParticipantsPanel._button(
            footer, "Закрыть", self._close, SURFACE_LIGHT, TEXT
        ).pack(side="right")
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        for widget in self.rows_frame.winfo_children():
            widget.destroy()
        corrections = sorted(
            self.app.nickname_corrections,
            key=lambda correction: nickname_lookup_key(correction.recognized),
        )
        self.count_label.configure(
            text=f"· {len(corrections)}" if corrections else ""
        )
        if not corrections:
            tk.Label(
                self.rows_frame,
                text="Сохранённых замен пока нет",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 11),
                pady=self._px(28),
            ).pack(fill="x")
        for correction in corrections:
            self._add_row(correction)
        self.canvas.yview_moveto(0.0)
        self.after_idle(self._update_scrollbar_visibility)

    def _add_row(self, correction: NicknameCorrection) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(
            row, bg=SURFACE, padx=self._px(16), pady=self._px(8)
        )
        content.pack(fill="x")
        content.grid_columnconfigure(0, weight=1, uniform="correction_values")
        content.grid_columnconfigure(2, weight=1, uniform="correction_values")
        recognized_label = tk.Label(
            content,
            text=correction.recognized,
            bg=SURFACE,
            fg=TEXT,
            anchor="w",
            font=("Segoe UI", 11),
        )
        recognized_label.grid(row=0, column=0, sticky="ew")
        arrow_label = tk.Label(
            content,
            text="⇆",
            bg=SURFACE,
            fg=ACCENT,
            font=("Segoe UI Symbol", 12),
            padx=self._px(14),
        )
        arrow_label.grid(row=0, column=1)
        replacement_label = tk.Label(
            content,
            text=correction.replacement,
            bg=SURFACE,
            fg=TEXT,
            anchor="w",
            font=("Segoe UI", 11),
        )
        replacement_label.grid(row=0, column=2, sticky="ew")
        delete = StyledDeleteButton(
            content,
            command=lambda name=correction.recognized: self._delete(name),
            background=SURFACE,
        )
        delete.grid(row=0, column=3, padx=(self._px(12), 0))
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(
            fill="x", padx=self._px(10)
        )

        def set_hover(hovered: bool) -> None:
            background = ROW_HOVER if hovered else SURFACE
            row.configure(bg=background)
            content.configure(bg=background)
            recognized_label.configure(bg=background)
            arrow_label.configure(bg=background)
            replacement_label.configure(bg=background)
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

        for widget in (row, content, recognized_label, arrow_label, replacement_label, delete):
            widget.bind("<Enter>", lambda _event: set_hover(True), add="+")
            widget.bind("<Leave>", lambda _event: set_hover(False), add="+")
            widget.bind("<MouseWheel>", self._scroll)

    def _delete(self, recognized_name: str) -> None:
        try:
            self.app.remove_nickname_correction(recognized_name)
        except OSError as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось удалить замену:\n{error}",
                parent=self,
            )
            return
        self._refresh_rows()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._update_scrollbar_visibility)

    def _resize_rows(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.rows_window, width=event.width)
        self.after_idle(self._update_scrollbar_visibility)

    def _update_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.canvas.winfo_height() + 1
        if should_show and not self._scrollbar_visible:
            self.scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
        elif not should_show and self._scrollbar_visible:
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _center_on_parent(self) -> None:
        self.update_idletasks()
        width = max(self._px(650), self.winfo_width())
        height = max(self._px(470), self.winfo_height())
        x = self.parent_dialog.winfo_rootx() + (
            self.parent_dialog.winfo_width() - width
        ) // 2
        y = self.parent_dialog.winfo_rooty() + (
            self.parent_dialog.winfo_height() - height
        ) // 2
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        apply_dark_title_bar(self)
        self.deiconify()
        self.after(10, self._finish_open)

    def _finish_open(self) -> None:
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _close(self) -> None:
        if getattr(self.parent_dialog, "corrections_dialog", None) is self:
            self.parent_dialog.corrections_dialog = None
        self.destroy()


class DateRangePicker(tk.Toplevel):
    MONTH_NAMES = (
        "ЯНВАРЬ",
        "ФЕВРАЛЬ",
        "МАРТ",
        "АПРЕЛЬ",
        "МАЙ",
        "ИЮНЬ",
        "ИЮЛЬ",
        "АВГУСТ",
        "СЕНТЯБРЬ",
        "ОКТЯБРЬ",
        "НОЯБРЬ",
        "ДЕКАБРЬ",
    )
    WEEKDAYS = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
    RANGE_BACKGROUND = "#38372D"

    def __init__(self, owner: "DrawHistoryDialog") -> None:
        super().__init__(owner)
        self.withdraw()
        self.owner = owner
        self.ui_scale = owner.ui_scale
        self.selected_start = owner.date_from
        self.selected_end = owner.date_to
        reference = self.selected_start or self._latest_result_date() or date.today()
        self.visible_month = reference.replace(day=1)
        self.day_cells: list[dict[str, object]] = []
        self._focus_after_id: str | None = None

        self.overrideredirect(True)
        self.configure(bg=BORDER_LIGHT)
        self.transient(owner)
        self.bind("<Escape>", lambda _event: self._close())
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self._build_ui()
        self._show_below_button()

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _latest_result_date(self) -> date | None:
        dates = [
            parsed
            for result in self.owner._results
            if (parsed := draw_result_date(result.timestamp)) is not None
        ]
        return max(dates) if dates else None

    def _build_ui(self) -> None:
        panel = tk.Frame(self, bg=PANEL_BACKGROUND)
        panel.pack(fill="both", expand=True, padx=self._px(1), pady=self._px(1))

        header = tk.Frame(panel, bg=PANEL_BACKGROUND)
        header.pack(fill="x", padx=self._px(14), pady=(self._px(12), self._px(8)))
        tk.Label(
            header,
            text="ПЕРИОД",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
        ).pack(side="left")
        close_button = StyledDeleteButton(
            header,
            command=self._close,
            background=PANEL_BACKGROUND,
        )
        close_button.pack(side="right")

        navigation = tk.Frame(panel, bg=PANEL_BACKGROUND)
        navigation.pack(fill="x", padx=self._px(14), pady=(0, self._px(8)))
        self._navigation_button(navigation, "‹", -1).pack(side="left")
        self.month_label = tk.Label(
            navigation,
            bg=PANEL_BACKGROUND,
            fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 11),
            anchor="center",
        )
        self.month_label.pack(side="left", fill="x", expand=True)
        self._navigation_button(navigation, "›", 1).pack(side="right")

        calendar_frame = tk.Frame(panel, bg=SURFACE)
        calendar_frame.pack(fill="both", expand=True, padx=self._px(14))
        for column in range(7):
            calendar_frame.grid_columnconfigure(column, weight=1, uniform="days")
        for column, weekday in enumerate(self.WEEKDAYS):
            tk.Label(
                calendar_frame,
                text=weekday,
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 8),
                pady=self._px(7),
            ).grid(row=0, column=column, sticky="nsew")

        for index in range(42):
            cell = tk.Label(
                calendar_frame,
                bg=SURFACE,
                fg=TEXT,
                font=("Segoe UI", 10),
                width=4,
                height=2,
                cursor="hand2",
                highlightthickness=1,
                highlightbackground=SURFACE,
            )
            cell.grid(
                row=index // 7 + 1,
                column=index % 7,
                sticky="nsew",
                padx=self._px(1),
                pady=self._px(1),
            )
            cell_data: dict[str, object] = {
                "widget": cell,
                "date": None,
                "hovered": False,
            }
            cell.bind(
                "<Button-1>",
                lambda _event, data=cell_data: self._select_day(data),
            )
            cell.bind(
                "<Enter>",
                lambda _event, data=cell_data: self._set_day_hover(data, True),
            )
            cell.bind(
                "<Leave>",
                lambda _event, data=cell_data: self._set_day_hover(data, False),
            )
            self.day_cells.append(cell_data)

        self.selection_label = tk.Label(
            panel,
            bg=PANEL_BACKGROUND,
            fg=ACCENT_HOVER,
            font=("Segoe UI Semibold", 10),
            anchor="center",
        )
        self.selection_label.pack(fill="x", padx=self._px(14), pady=self._px(10))

        footer = tk.Frame(panel, bg=PANEL_BACKGROUND)
        footer.pack(fill="x", padx=self._px(14), pady=(0, self._px(14)))
        self._action_button(
            footer,
            "Сбросить",
            self._clear,
            SURFACE_LIGHT,
            TEXT,
        ).pack(side="left")
        self.apply_button = self._action_button(
            footer,
            "Применить",
            self._apply,
            ACCENT,
            TEXT_BRIGHT,
        )
        self.apply_button.pack(side="right")
        self._redraw_calendar()

    def _navigation_button(
        self,
        parent: tk.Misc,
        text: str,
        offset: int,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=lambda: self._change_month(offset),
            bg=SURFACE_LIGHT,
            fg=TEXT,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_BRIGHT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BUTTON_BORDER,
            cursor="hand2",
            font=("Segoe UI Symbol", 13),
            padx=self._px(10),
            pady=self._px(1),
        )
        return button

    def _action_button(
        self,
        parent: tk.Misc,
        text: str,
        command: object,
        background: str,
        foreground: str,
    ) -> tk.Button:
        accent = background == ACCENT
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=ACCENT_HOVER if accent else BUTTON_HOVER,
            activeforeground=TEXT_BRIGHT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=ACCENT_DARK if accent else BUTTON_BORDER,
            disabledforeground=DISABLED_TEXT,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            padx=self._px(12),
            pady=self._px(6),
        )
        return button

    def _change_month(self, offset: int) -> None:
        month_index = self.visible_month.year * 12 + self.visible_month.month - 1
        month_index += offset
        year, month_zero_based = divmod(month_index, 12)
        self.visible_month = date(year, month_zero_based + 1, 1)
        self._redraw_calendar()

    def _select_day(self, cell_data: dict[str, object]) -> None:
        selected = cell_data.get("date")
        if not isinstance(selected, date):
            return
        if self.selected_start is None or self.selected_end is not None:
            self.selected_start = selected
            self.selected_end = None
        elif selected < self.selected_start:
            self.selected_end = self.selected_start
            self.selected_start = selected
        else:
            self.selected_end = selected
        self._redraw_calendar()

    def _set_day_hover(
        self,
        cell_data: dict[str, object],
        hovered: bool,
    ) -> None:
        cell_data["hovered"] = hovered
        self._style_day(cell_data)

    def _style_day(self, cell_data: dict[str, object]) -> None:
        widget = cell_data.get("widget")
        value = cell_data.get("date")
        if not isinstance(widget, tk.Label):
            return
        if not isinstance(value, date):
            widget.configure(
                text="",
                bg=SURFACE,
                highlightbackground=SURFACE,
                cursor="arrow",
            )
            return

        is_endpoint = value in (self.selected_start, self.selected_end)
        in_range = (
            self.selected_start is not None
            and self.selected_end is not None
            and self.selected_start <= value <= self.selected_end
        )
        if is_endpoint:
            background = ACCENT
            foreground = TEXT_BRIGHT
        elif in_range:
            background = self.RANGE_BACKGROUND
            foreground = TEXT_BRIGHT
        elif bool(cell_data.get("hovered")):
            background = ROW_HOVER
            foreground = TEXT_BRIGHT
        else:
            background = SURFACE
            foreground = TEXT
        widget.configure(
            text=str(value.day),
            bg=background,
            fg=foreground,
            cursor="hand2",
            highlightbackground=(
                BRAND_GREEN_LIGHT if value == date.today() else background
            ),
        )

    def _redraw_calendar(self) -> None:
        self.month_label.configure(
            text=f"{self.MONTH_NAMES[self.visible_month.month - 1]} {self.visible_month.year}"
        )
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
            self.visible_month.year,
            self.visible_month.month,
        )
        visible_dates = [value for week in weeks for value in week]
        for index, cell_data in enumerate(self.day_cells):
            value = visible_dates[index] if index < len(visible_dates) else None
            if value is not None and value.month != self.visible_month.month:
                value = None
            cell_data["date"] = value
            self._style_day(cell_data)

        if self.selected_start is None:
            selection_text = "Период не выбран"
        elif self.selected_end is None:
            selection_text = self.selected_start.strftime("%d.%m.%Y — …")
        else:
            selection_text = (
                f"{self.selected_start:%d.%m.%Y} — {self.selected_end:%d.%m.%Y}"
            )
        self.selection_label.configure(text=selection_text)
        self.apply_button.configure(
            state="normal" if self.selected_start is not None else "disabled",
            cursor="hand2" if self.selected_start is not None else "arrow",
        )

    def _apply(self) -> None:
        if self.selected_start is None:
            return
        end = self.selected_end or self.selected_start
        self.owner.set_date_filter(self.selected_start, end)
        self._close()

    def _clear(self) -> None:
        self.owner.set_date_filter(None, None)
        self._close()

    def _show_below_button(self) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        button = self.owner.calendar_button
        x = button.winfo_rootx() + button.winfo_width() - width
        y = button.winfo_rooty() + button.winfo_height() + self._px(6)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = min(max(0, x), max(0, screen_width - width))
        y = min(max(0, y), max(0, screen_height - height))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_focus_out(self, _event: tk.Event[tk.Misc]) -> None:
        if self._focus_after_id is not None:
            self.after_cancel(self._focus_after_id)
        self._focus_after_id = self.after(60, self._close_if_focus_lost)

    def _close_if_focus_lost(self) -> None:
        self._focus_after_id = None
        if not self.winfo_exists():
            return
        focused = self.focus_displayof()
        if focused is None or focused.winfo_toplevel() is not self:
            self._close(restore_focus=False)

    def _close(self, restore_focus: bool = True) -> None:
        if self._focus_after_id is not None:
            try:
                self.after_cancel(self._focus_after_id)
            except tk.TclError:
                pass
            self._focus_after_id = None
        if getattr(self.owner, "date_picker", None) is self:
            self.owner.date_picker = None
        self.destroy()
        if restore_focus:
            self.owner._schedule_focus_after_date_picker()


class DrawHistoryDialog(tk.Toplevel):
    def __init__(self, owner: "ParticipantsPanel") -> None:
        super().__init__(owner.winfo_toplevel())
        self.withdraw()
        self.owner = owner
        self.app = owner.owner
        self.ui_scale = float(getattr(owner, "ui_scale", 1.0))
        self._scrollbar_visible = False
        self._layout_after_id: str | None = None
        self._focus_restore_after_id: str | None = None
        self._center_after_id: str | None = None
        self._open_after_id: str | None = None
        self.search_var = tk.StringVar()
        self._results: list[DrawResult] = []
        self.date_from: date | None = None
        self.date_to: date | None = None
        self.date_picker: DateRangePicker | None = None
        self._calendar_hovered = False
        if os.name == "nt":
            self.attributes("-alpha", 0.0)

        self.title("История розыгрышей")
        apply_window_icon(self)
        self.geometry(f"{self._px(900)}x{self._px(580)}")
        self.minsize(self._px(720), self._px(420))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(owner.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._build_ui()
        self.search_var.trace_add("write", self._on_search_changed)
        self._center_after_id = self.after_idle(self._center_on_application)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _configure_columns(self, frame: tk.Misc) -> None:
        frame.grid_columnconfigure(0, weight=2, uniform="history_columns")
        frame.grid_columnconfigure(1, weight=7, uniform="history_columns")
        frame.grid_columnconfigure(
            2,
            weight=2,
            minsize=self._px(155),
            uniform="history_columns",
        )
        frame.grid_columnconfigure(3, weight=0, minsize=self._px(42))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=PANEL_BACKGROUND)
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(20), self._px(12)),
        )
        tk.Label(
            header,
            text="ИСТОРИЯ РОЗЫГРЫШЕЙ",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left")
        self.count_label = tk.Label(
            header,
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 12),
        )
        self.count_label.pack(
            side="left",
            padx=(self._px(8), 0),
            pady=(self._px(2), 0),
        )

        search_group = tk.Frame(header, bg=PANEL_BACKGROUND)
        search_group.pack(side="right", fill="y")
        tk.Label(
            search_group,
            text="ПОИСК",
            bg=PANEL_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left", padx=(0, self._px(9)))
        search_field = tk.Frame(
            search_group,
            bg=INPUT_BACKGROUND,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        search_field.pack(side="left", fill="y")
        self.search_entry = tk.Entry(
            search_field,
            textvariable=self.search_var,
            width=28,
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=BRAND_GREEN,
            selectforeground=TEXT_BRIGHT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
        )
        enable_entry_shortcuts(self.search_entry)
        self.search_entry.pack(
            fill="both",
            expand=True,
            padx=self._px(9),
            ipady=self._px(5),
        )
        self.search_entry.bind(
            "<FocusIn>",
            lambda _event: search_field.configure(
                highlightbackground=BORDER_LIGHT
            ),
            add="+",
        )
        self.search_entry.bind(
            "<FocusOut>",
            lambda _event: search_field.configure(highlightbackground=BORDER),
            add="+",
        )
        self.calendar_button = tk.Canvas(
            search_group,
            width=self._px(38),
            height=self._px(34),
            bg=PANEL_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.calendar_button.pack(side="left", padx=(self._px(8), 0))
        self.calendar_button.bind("<Button-1>", self._open_date_picker)
        self.calendar_button.bind("<Return>", self._open_date_picker)
        self.calendar_button.bind("<space>", self._open_date_picker)
        self.calendar_button.bind(
            "<Enter>", lambda _event: self._set_calendar_hover(True)
        )
        self.calendar_button.bind(
            "<Leave>", lambda _event: self._set_calendar_hover(False)
        )
        self.calendar_button.bind("<FocusIn>", self._draw_calendar_button)
        self.calendar_button.bind("<FocusOut>", self._draw_calendar_button)
        self._draw_calendar_button()

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(
            fill="both",
            expand=True,
            padx=self._px(22),
            pady=(0, self._px(22)),
        )

        columns_header = tk.Frame(
            list_shell,
            bg=SURFACE,
            height=self._px(30),
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        self._configure_columns(columns_header)
        for column, text in enumerate(("ИГРОК", "ПРИЗ", "ДАТА")):
            tk.Label(
                columns_header,
                text=text,
                bg=SURFACE,
                fg=MUTED,
                anchor="w",
                font=("Segoe UI Semibold", 9),
            ).grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(self._px(16), self._px(6)),
                pady=(self._px(7), self._px(4)),
            )
        tk.Frame(list_shell, bg="#343B36", height=self._px(1)).pack(fill="x")

        body = tk.Frame(list_shell, bg=SURFACE)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            body,
            bg=SURFACE,
            highlightthickness=0,
            borderwidth=0,
        )
        self.scrollbar = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_window = self.canvas.create_window(
            (0, 0),
            window=self.rows_frame,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)

        self.refresh()

    def refresh(self) -> None:
        try:
            self._results = self.app.draw_log_store.load()
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось прочитать журнал розыгрышей:\n{error}",
                parent=self,
            )
            self._results = []

        self._render_results()

    def _on_search_changed(self, *_args: object) -> None:
        self._render_results()

    def _render_results(self) -> None:
        for widget in self.rows_frame.winfo_children():
            widget.destroy()

        terms = self.search_var.get().casefold().split()
        visible_results = [
            (index, result)
            for index, result in enumerate(self._results)
            if self._matches_date_filter(result)
            and (
                not terms
                or all(
                    term in f"{result.winner}\n{result.reward}".casefold()
                    for term in terms
                )
            )
        ]
        total = len(self._results)
        visible_count = len(visible_results)
        date_filter_active = self.date_from is not None or self.date_to is not None
        if terms or date_filter_active:
            self.count_label.configure(text=f"· {visible_count} из {total}")
        else:
            self.count_label.configure(text=f"· {total}" if total else "")

        if not visible_results:
            tk.Label(
                self.rows_frame,
                text=(
                    "Совпадений не найдено"
                    if terms
                    else (
                        "За выбранный период записей нет"
                        if date_filter_active
                        else "История розыгрышей пока пуста"
                    )
                ),
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 11),
                pady=self._px(28),
            ).pack(fill="x")
        for index, result in reversed(visible_results):
            self._add_row(index, result)
        self.canvas.yview_moveto(0.0)
        self._schedule_layout_update()

    def _matches_date_filter(self, result: DrawResult) -> bool:
        if self.date_from is None and self.date_to is None:
            return True
        result_day = draw_result_date(result.timestamp)
        if result_day is None:
            return False
        if self.date_from is not None and result_day < self.date_from:
            return False
        if self.date_to is not None and result_day > self.date_to:
            return False
        return True

    def set_date_filter(
        self,
        start: date | None,
        end: date | None,
    ) -> None:
        if start is not None and end is not None and end < start:
            start, end = end, start
        self.date_from = start
        self.date_to = end
        self._draw_calendar_button()
        self._render_results()

    def _open_date_picker(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> str:
        if self.date_picker is not None and self.date_picker.winfo_exists():
            self.date_picker._close()
            return "break"
        self.date_picker = DateRangePicker(self)
        return "break"

    def _set_calendar_hover(self, hovered: bool) -> None:
        self._calendar_hovered = hovered
        self._draw_calendar_button()

    def _draw_calendar_button(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        button = self.calendar_button
        button.delete("all")
        px = self._px
        width = px(38)
        height = px(34)
        active_filter = self.date_from is not None or self.date_to is not None
        focused = button.focus_get() is button
        hovered = self._calendar_hovered or focused
        border = ACCENT if active_filter else (BORDER_LIGHT if hovered else BORDER)
        icon = ACCENT_HOVER if active_filter else (TEXT if hovered else MUTED)
        button.create_rectangle(
            px(1),
            px(1),
            width - px(1),
            height - px(1),
            fill=SURFACE_LIGHT if hovered or active_filter else SURFACE,
            outline=border,
            width=px(1),
        )
        left, top, right, bottom = px(10), px(9), px(28), px(26)
        button.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=icon,
            width=px(2),
        )
        button.create_line(left, px(14), right, px(14), fill=icon, width=px(2))
        for x in (px(14), px(24)):
            button.create_line(
                x,
                px(6),
                x,
                px(11),
                fill=icon,
                width=px(2),
                capstyle="round",
            )
        for x in (px(15), px(21), px(25)):
            button.create_oval(
                x - px(1),
                px(18),
                x + px(1),
                px(20),
                fill=icon,
                outline=icon,
            )

    def _add_row(self, index: int, result: DrawResult) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(
            row,
            bg=SURFACE,
            padx=self._px(10),
            pady=self._px(8),
        )
        content.pack(fill="x")
        self._configure_columns(content)

        fields: list[tk.Entry] = []
        for column, (value, color, font) in enumerate(
            (
                (result.winner, TEXT, ("Segoe UI", 11)),
                (result.reward, TEXT, ("Segoe UI", 11)),
                (
                    format_draw_timestamp(result.timestamp),
                    MUTED,
                    ("Segoe UI", 10),
                ),
            )
        ):
            field = tk.Entry(
                content,
                bg=SURFACE,
                readonlybackground=SURFACE,
                fg=color,
                insertbackground=TEXT,
                selectbackground=BRAND_GREEN,
                selectforeground=TEXT_BRIGHT,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                font=font,
                state="normal",
                cursor="xterm",
            )
            field.insert(0, value)
            field.configure(state="readonly")
            enable_entry_shortcuts(field)
            field.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(self._px(6), self._px(8)),
            )
            fields.append(field)

        delete = StyledDeleteButton(
            content,
            command=lambda item_index=index: self._delete(item_index),
            background=SURFACE,
        )
        delete.grid(row=0, column=3, padx=(self._px(4), 0))
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(
            fill="x",
            padx=self._px(10),
        )

        def set_hover(hovered: bool) -> None:
            background = ROW_HOVER if hovered else SURFACE
            row.configure(bg=background)
            content.configure(bg=background)
            for field in fields:
                field.configure(readonlybackground=background)
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

        for widget in (row, content, *fields, delete):
            widget.bind(
                "<Enter>",
                lambda _event: set_hover(True),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event: set_hover(False),
                add="+",
            )
            widget.bind("<MouseWheel>", self._scroll)

    def _delete(self, index: int) -> None:
        if not 0 <= index < len(self._results):
            return
        result = self._results[index]
        confirmed = messagebox.askyesno(
            "Удаление записи",
            (
                f"Удалить запись о розыгрыше для игрока «{result.winner}»?\n\n"
                "Запись будет удалена из истории и файла журнала."
            ),
            icon="warning",
            parent=self,
        )
        if not confirmed:
            return
        try:
            self.app.draw_log_store.remove_at(index)
        except (OSError, ValueError, TypeError, IndexError) as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось удалить запись:\n{error}",
                parent=self,
            )
            return
        self.refresh()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._schedule_layout_update()

    def _resize_rows(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.rows_window, width=event.width)
        self._schedule_layout_update()

    def _schedule_layout_update(self) -> None:
        if self._layout_after_id is None:
            self._layout_after_id = self.after_idle(
                self._run_scheduled_layout_update
            )

    def _run_scheduled_layout_update(self) -> None:
        self._layout_after_id = None
        if self.winfo_exists():
            self._update_scrollbar_visibility()

    def _cancel_layout_update(self) -> None:
        if self._layout_after_id is None:
            return
        try:
            self.after_cancel(self._layout_after_id)
        except tk.TclError:
            pass
        self._layout_after_id = None

    def _schedule_focus_after_date_picker(self) -> None:
        self._cancel_focus_restore()
        self._focus_restore_after_id = self.after_idle(
            self._restore_focus_after_date_picker
        )

    def _restore_focus_after_date_picker(self) -> None:
        self._focus_restore_after_id = None
        try:
            if not self.winfo_exists():
                return
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _cancel_focus_restore(self) -> None:
        if self._focus_restore_after_id is None:
            return
        try:
            self.after_cancel(self._focus_restore_after_id)
        except tk.TclError:
            pass
        self._focus_restore_after_id = None

    def _synchronize_rows_layout(self) -> None:
        """Match the history rows to the final canvas width."""

        self.canvas.itemconfigure(
            self.rows_window,
            width=max(1, self.canvas.winfo_width()),
        )
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _update_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.canvas.winfo_height() + 1
        visibility_changed = False
        if should_show and not self._scrollbar_visible:
            self.scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
            visibility_changed = True
        elif not should_show and self._scrollbar_visible:
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False
            visibility_changed = True
        if visibility_changed:
            self._schedule_layout_update()

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _center_on_application(self) -> None:
        self._center_after_id = None
        self.update_idletasks()
        application = self.owner.winfo_toplevel()
        width = max(self._px(900), self.winfo_width())
        height = max(self._px(580), self.winfo_height())
        x = application.winfo_rootx() + (application.winfo_width() - width) // 2
        y = application.winfo_rooty() + (application.winfo_height() - height) // 2
        self._open_geometry = f"{width}x{height}+{max(0, x)}+{max(0, y)}"

        # On Windows the native frame can be recreated by deiconify() before
        # DWM has restored its dark attributes.  Prepare that first mapped
        # frame off-screen so a default white caption can never be visible.
        if os.name == "nt":
            self.geometry(f"{width}x{height}-32000-32000")
        else:
            self.geometry(self._open_geometry)
        apply_dark_title_bar(self)
        self.deiconify()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.update_idletasks()
        apply_dark_title_bar(self)
        self._open_after_id = self.after(30, self._finish_open)

    def _finish_open(self) -> None:
        self._open_after_id = None
        apply_dark_title_bar(self)
        self.geometry(self._open_geometry)
        self.update_idletasks()
        self._update_scrollbar_visibility()
        self.update_idletasks()
        self._synchronize_rows_layout()
        self.update_idletasks()
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _close(self) -> None:
        self._cancel_open_callbacks()
        self._cancel_layout_update()
        self._cancel_focus_restore()
        if self.date_picker is not None and self.date_picker.winfo_exists():
            self.date_picker._close(restore_focus=False)
        if getattr(self.owner, "history_dialog", None) is self:
            self.owner.history_dialog = None
        self.destroy()

    def _on_destroy(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is self:
            self._cancel_open_callbacks()
            self._cancel_layout_update()
            self._cancel_focus_restore()

    def _cancel_open_callbacks(self) -> None:
        for attribute in ("_center_after_id", "_open_after_id"):
            callback_id = getattr(self, attribute, None)
            if callback_id is None:
                continue
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)


class ScreenshotImportDialog(tk.Toplevel):
    THUMBNAIL_WIDTH = 310
    THUMBNAIL_HEIGHT = 170

    def __init__(self, owner: "ParticipantsPanel") -> None:
        super().__init__(owner.winfo_toplevel())
        self.withdraw()
        self.ui_scale = float(getattr(owner.owner, "ui_scale", 1.0))
        self.thumbnail_width = self._px(self.THUMBNAIL_WIDTH)
        self.thumbnail_height = self._px(self.THUMBNAIL_HEIGHT)
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.owner = owner
        self.screenshots: list[Image.Image] = []
        self.rows: list[dict[str, object]] = []
        self.corrections_dialog: NicknameCorrectionsDialog | None = None
        self.ocr_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.view = "screenshots"
        self._scrollbar_visible = False
        self.loading_text = AnimatedEllipsis(self)
        self._clipboard_watch_after_id: str | None = None
        self._clipboard_was_foreground = False
        self._clipboard_sequence_before_blur = clipboard_sequence_number()
        self._last_imported_clipboard_sequence = 0

        self.title("Импорт из буфера")
        apply_window_icon(self)
        self.geometry(f"{self._px(760)}x{self._px(660)}")
        self.minsize(self._px(700), self._px(540))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(owner.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self.bind("<Control-KeyPress>", self._on_control_keypress)
        self._build_ui()
        self._prioritize_keyboard_shortcuts()
        self._show_screenshot_view()
        self.after_idle(self._center_on_application)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=PANEL_BACKGROUND)
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(20), self._px(12)),
        )
        tk.Label(
            header,
            text="ИМПОРТ ИЗ БУФЕРА",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left")
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 12),
        )
        self.status_label.pack(
            side="left", padx=(self._px(8), 0), pady=(self._px(2), 0)
        )
        self.paste_button = ParticipantsPanel._button(
            header, "Вставить скриншот", self._paste, SURFACE_LIGHT, TEXT
        )
        self.paste_button.pack(side="right")
        self.corrections_button = ParticipantsPanel._button(
            header, "⇆", self._open_corrections, SURFACE_LIGHT, TEXT
        )
        self.corrections_button.configure(
            font=("Segoe UI Symbol", 13),
            padx=self._px(13),
            pady=self._px(3),
        )
        self.corrections_button.pack(
            side="right", fill="y", padx=(0, self._px(8))
        )

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(fill="both", expand=True, padx=self._px(22))
        self.canvas = tk.Canvas(
            list_shell, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            list_shell, orient="vertical", command=self.canvas.yview
        )
        self.content_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.content_window = self.canvas.create_window(
            (0, 0), window=self.content_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind("<MouseWheel>", self._scroll)

        footer = tk.Frame(self, bg=PANEL_BACKGROUND)
        footer.pack(
            fill="x", padx=self._px(22), pady=self._px(18)
        )
        self.back_button = ParticipantsPanel._button(
            footer, "К скриншотам", self._show_screenshot_view, SURFACE_LIGHT, TEXT
        )
        ParticipantsPanel._button(
            footer, "Отмена", self._close, PANEL_BACKGROUND, MUTED
        ).pack(side="right", padx=(self._px(8), 0))
        self.action_button = ParticipantsPanel._button(
            footer, "Распознать", self._recognize, SURFACE_LIGHT, TEXT
        )
        self.action_button.pack(side="right")

    def _paste(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self.busy:
            return "break"
        try:
            image = clipboard_image()
        except OcrError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self)
            return "break"

        self.screenshots.append(image.copy())
        self._last_imported_clipboard_sequence = clipboard_sequence_number()
        self._show_screenshot_view()
        return "break"

    def _on_control_keypress(self, event: tk.Event[tk.Misc]) -> str | None:
        if isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return None
        keysym = str(getattr(event, "keysym", "")).casefold()
        keycode = int(getattr(event, "keycode", 0) or 0)
        if keycode == 86 or keysym in {"v", "м", "cyrillic_em"}:
            return self._paste(event)
        return None

    def _prioritize_keyboard_shortcuts(self) -> None:
        """Handle dialog shortcuts before focused Entry and Canvas classes."""

        dialog_tag = str(self)

        def visit(widget: tk.Misc) -> None:
            try:
                tags = tuple(str(tag) for tag in widget.bindtags())
                widget.bindtags(
                    (dialog_tag,) + tuple(tag for tag in tags if tag != dialog_tag)
                )
                children = widget.winfo_children()
            except tk.TclError:
                return
            for child in children:
                visit(child)

        visit(self)

    def _open_corrections(self) -> None:
        if self.busy:
            return
        if (
            self.corrections_dialog is not None
            and self.corrections_dialog.winfo_exists()
        ):
            self.corrections_dialog.deiconify()
            self.corrections_dialog.lift()
            self.corrections_dialog.focus_force()
            return
        self.corrections_dialog = NicknameCorrectionsDialog(
            self, self.owner.owner
        )

    def _show_screenshot_view(self) -> None:
        if self.busy:
            return
        self.view = "screenshots"
        self.rows.clear()
        self._clear_content()
        self.content_frame.grid_columnconfigure(0, weight=1, uniform="screenshots")
        self.content_frame.grid_columnconfigure(1, weight=1, uniform="screenshots")

        for index, screenshot in enumerate(self.screenshots):
            self._add_thumbnail(screenshot, index)

        count = len(self.screenshots)
        self.status_var.set(f"· {count}" if count else "")
        self.paste_button.configure(state="normal", text="Вставить скриншот")
        self.corrections_button.configure(state="normal")
        self.action_button.configure(
            text="Распознать",
            command=self._recognize,
            state="normal" if count else "disabled",
        )
        self.back_button.pack_forget()
        self.canvas.yview_moveto(0.0)
        self.after_idle(self._prioritize_keyboard_shortcuts)
        self.after_idle(self._update_scrollbar_visibility)

    def _add_thumbnail(self, screenshot: Image.Image, index: int) -> None:
        preview = screenshot.convert("RGB")
        preview.thumbnail(
            (self._px(290), self._px(150)), Image.Resampling.LANCZOS
        )
        dim_layer = Image.new("RGB", preview.size, BACKGROUND)
        dimmed = Image.blend(preview, dim_layer, 0.58)
        normal_photo = ImageTk.PhotoImage(preview)
        dimmed_photo = ImageTk.PhotoImage(dimmed)

        card = tk.Canvas(
            self.content_frame,
            width=self.thumbnail_width,
            height=self.thumbnail_height,
            bg=SURFACE_LIGHT,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        card.grid(
            row=index // 2,
            column=index % 2,
            padx=self._px(8),
            pady=self._px(8),
        )
        card.create_rectangle(
            1,
            1,
            self.thumbnail_width - self._px(1),
            self.thumbnail_height - self._px(1),
            outline=BUTTON_BORDER,
            width=self._px(2),
        )
        image_item = card.create_image(
            self.thumbnail_width // 2,
            self.thumbnail_height // 2,
            image=normal_photo,
        )
        card.normal_photo = normal_photo  # type: ignore[attr-defined]
        card.dimmed_photo = dimmed_photo  # type: ignore[attr-defined]

        def show_delete(_event: tk.Event[tk.Misc]) -> None:
            card.itemconfigure(image_item, image=card.dimmed_photo)  # type: ignore[attr-defined]
            center_x = self.thumbnail_width // 2
            center_y = self.thumbnail_height // 2
            card.create_line(
                center_x - self._px(15),
                center_y - self._px(15),
                center_x + self._px(15),
                center_y + self._px(15),
                fill=TEXT,
                width=self._px(4),
                capstyle="round",
                tags="delete_overlay",
            )
            card.create_line(
                center_x + self._px(15),
                center_y - self._px(15),
                center_x - self._px(15),
                center_y + self._px(15),
                fill=TEXT,
                width=self._px(4),
                capstyle="round",
                tags="delete_overlay",
            )

        def hide_delete(_event: tk.Event[tk.Misc]) -> None:
            card.itemconfigure(image_item, image=card.normal_photo)  # type: ignore[attr-defined]
            card.delete("delete_overlay")

        card.bind("<Enter>", show_delete)
        card.bind("<Leave>", hide_delete)
        card.bind(
            "<Button-1>",
            lambda _event, image=screenshot: self._delete_screenshot(image),
        )
        card.bind("<MouseWheel>", self._scroll)

    def _delete_screenshot(self, screenshot: Image.Image) -> None:
        if self.busy:
            return
        for index, current in enumerate(self.screenshots):
            if current is screenshot:
                del self.screenshots[index]
                break
        self._show_screenshot_view()

    def _recognize(self) -> None:
        if self.busy or not self.screenshots:
            return
        self.busy = True
        self.paste_button.configure(state="disabled")
        self.corrections_button.configure(state="disabled")
        self.action_button.configure(state="disabled")
        self.loading_text.start(self.action_button, "Распознавание")
        images = [image.copy() for image in self.screenshots]

        def worker() -> None:
            try:
                result: list[RecognizedParticipant] = []
                for image in images:
                    result.extend(recognize_participants(image))
                self.ocr_queue.put(("result", result))
            except Exception as error:
                self.ocr_queue.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_ocr)
        return "break"

    def _poll_ocr(self) -> None:
        try:
            kind, payload = self.ocr_queue.get_nowait()
        except queue.Empty:
            if self.busy:
                self.after(100, self._poll_ocr)
            return

        self.busy = False
        self.loading_text.stop()
        if kind == "error":
            self._show_screenshot_view()
            messagebox.showerror(
                APP_NAME,
                str(payload) or "Не удалось распознать изображение.",
                parent=self,
            )
            return

        recognized = payload if isinstance(payload, list) else []
        if not recognized:
            self._show_screenshot_view()
            messagebox.showwarning(
                APP_NAME, "На изображении не найдены участники.", parent=self
            )
            return
        self._show_results()
        for participant in recognized:
            if isinstance(participant, RecognizedParticipant):
                self._merge_or_add(participant)
        self.status_var.set(f"· {len(self.rows)}")
        self.action_button.configure(state="normal" if self.rows else "disabled")

    def _show_results(self) -> None:
        self.view = "results"
        self.rows.clear()
        self._clear_content()
        self.paste_button.configure(state="normal", text="Вставить скриншот")
        self.corrections_button.configure(state="normal")
        self.action_button.configure(
            text="Добавить",
            command=self._apply,
            state="disabled",
        )
        columns_header = tk.Frame(
            self.content_frame, bg=SURFACE, height=self._px(28)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        tk.Label(
            columns_header,
            text="ИГРОК",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(
            side="left",
            padx=(self._px(20), 0),
            pady=(self._px(7), self._px(4)),
        )
        tk.Label(
            columns_header,
            text="БМ",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(
            side="right",
            padx=(0, self._px(58)),
            pady=(self._px(7), self._px(4)),
        )
        tk.Frame(
            self.content_frame, bg="#343B36", height=self._px(1)
        ).pack(fill="x")
        self.back_button.pack(side="left")
        self.canvas.yview_moveto(0.0)
        self.after_idle(self._prioritize_keyboard_shortcuts)

    def _merge_or_add(self, participant: RecognizedParticipant) -> bool:
        recognized_name = clean_nickname(participant.name)
        corrected_name = self.owner.owner.corrected_nickname(recognized_name)
        new_name = self._normalized_participant_name(corrected_name)
        for row in self.rows:
            name_var = row.get("name")
            bm_var = row.get("bm")
            confidence = float(row.get("confidence", 0.0))
            if not isinstance(name_var, tk.StringVar) or not isinstance(
                bm_var, tk.StringVar
            ):
                continue
            current_name = self._normalized_participant_name(name_var.get())
            try:
                current_bm = int(bm_var.get().replace(" ", ""))
            except ValueError:
                current_bm = -1
            similarity = SequenceMatcher(None, current_name, new_name).ratio()
            same_person = current_name == new_name or (
                current_bm == participant.bm and similarity >= 0.72
            )
            if same_person:
                if (
                    participant.confidence > confidence
                    and not bool(row.get("name_edited"))
                ):
                    row["recognized_name"] = recognized_name
                    row["initial_name"] = corrected_name
                    name_var.set(corrected_name)
                    row["name_edited"] = False
                    bm_var.set(format_bm(float(participant.bm)))
                    row["confidence"] = participant.confidence
                return False
        self._add_result_row(participant, corrected_name, recognized_name)
        return True

    def _add_result_row(
        self,
        participant: RecognizedParticipant,
        corrected_name: str,
        recognized_name: str,
    ) -> None:
        row = tk.Frame(self.content_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(
            row, bg=SURFACE, padx=self._px(12), pady=self._px(3)
        )
        content.pack(fill="x")
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(
            fill="x", padx=self._px(10)
        )

        name_var = tk.StringVar(value=corrected_name)
        normal_name_border = (
            DANGER if participant.confidence < 55 else BORDER
        )
        name_field = tk.Frame(
            content,
            bg=SURFACE,
            highlightthickness=1 if participant.confidence < 55 else 0,
            highlightbackground=normal_name_border,
        )
        name_field.pack(side="left", fill="x", expand=True)
        name_entry = tk.Entry(
            name_field,
            textvariable=name_var,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 11),
            highlightthickness=0,
        )
        enable_entry_shortcuts(name_entry)
        name_entry.pack(
            side="left", fill="both", expand=True, ipady=self._px(7)
        )
        new_badge = tk.Label(
            name_field,
            text="NEW",
            bg=ACCENT,
            fg=BACKGROUND,
            font=("Segoe UI Semibold", 8),
            padx=self._px(7),
            pady=self._px(2),
        )
        update_badge = tk.Label(
            name_field,
            text="UPD",
            bg=SUCCESS,
            fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 8),
            padx=self._px(7),
            pady=self._px(2),
        )
        bm_var = tk.StringVar(value=format_bm(float(participant.bm)))
        bm_entry = tk.Entry(
            content,
            textvariable=bm_var,
            width=10,
            justify="right",
            bg=SURFACE,
            fg=MUTED,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=0,
            highlightbackground=SURFACE,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(bm_entry)
        bm_entry.pack(
            side="left",
            padx=(self._px(12), 0),
            ipady=self._px(7),
        )
        row_data: dict[str, object] = {
            "frame": row,
            "content": content,
            "name": name_var,
            "name_entry": name_entry,
            "name_field": name_field,
            "bm": bm_var,
            "bm_entry": bm_entry,
            "confidence": participant.confidence,
            "recognized_name": recognized_name,
            "initial_name": corrected_name,
            "name_edited": False,
            "hovered": False,
        }
        delete_button = StyledDeleteButton(
            content,
            command=lambda data=row_data: self._delete_row(data),
            background=SURFACE,
        )
        delete_button.pack(side="right", padx=(self._px(10), 0))
        row_data["delete"] = delete_button
        row_data["new_badge"] = new_badge
        row_data["update_badge"] = update_badge
        self.rows.append(row_data)
        name_var.trace_add(
            "write",
            lambda *_args, data=row_data: self._on_result_name_changed(data),
        )
        bm_var.trace_add(
            "write",
            lambda *_args, data=row_data: self._update_result_badges(data),
        )
        self._update_result_badges(row_data)
        name_entry.bind(
            "<FocusIn>",
            lambda _event, data=row_data: self._set_result_entry_focus(
                data, True, True
            ),
        )
        name_entry.bind(
            "<FocusOut>",
            lambda _event, data=row_data: self._set_result_entry_focus(
                data, False, True
            ),
        )
        bm_entry.bind(
            "<FocusIn>",
            lambda _event, data=row_data: self._set_result_entry_focus(
                data, True, False
            ),
        )
        bm_entry.bind(
            "<FocusOut>",
            lambda _event, data=row_data: self._finish_result_bm_edit(data),
        )
        hover_widgets = (
            row,
            content,
            name_field,
            name_entry,
            new_badge,
            update_badge,
            bm_entry,
            delete_button,
        )
        for widget in hover_widgets:
            widget.bind(
                "<Enter>",
                lambda _event, data=row_data: self._set_result_row_hover(
                    data, True
                ),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event, data=row_data: self.after_idle(
                    lambda item=data: self._finish_result_row_leave(item)
                ),
                add="+",
            )
            widget.bind("<MouseWheel>", self._scroll)
        self._update_result_row_appearance(row_data)
        self.after_idle(self._prioritize_keyboard_shortcuts)
        self.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def _set_result_entry_focus(
        self,
        row_data: dict[str, object],
        focused: bool,
        name_field: bool,
    ) -> None:
        field = row_data.get("name_field")
        name_entry = row_data.get("name_entry")
        bm_entry = row_data.get("bm_entry")
        if name_field and isinstance(field, tk.Frame) and isinstance(
            name_entry, tk.Entry
        ):
            if focused:
                field.configure(
                    bg=INPUT_BACKGROUND,
                    highlightthickness=1,
                    highlightbackground=BORDER_LIGHT,
                )
                name_entry.configure(bg=INPUT_BACKGROUND)
            else:
                self._update_result_row_appearance(row_data)
        elif not name_field and isinstance(bm_entry, tk.Entry):
            if focused:
                bm_entry.configure(
                    bg=INPUT_BACKGROUND,
                    fg=TEXT,
                    highlightthickness=1,
                    highlightbackground=BORDER_LIGHT,
                )
            else:
                self._update_result_row_appearance(row_data)

    def _finish_result_bm_edit(self, row_data: dict[str, object]) -> None:
        bm_var = row_data.get("bm")
        if isinstance(bm_var, tk.StringVar):
            try:
                bm_var.set(format_bm(parse_bm(bm_var.get())))
            except ValueError:
                pass
        self._set_result_entry_focus(row_data, False, False)

    def _update_result_row_appearance(
        self, row_data: dict[str, object]
    ) -> None:
        background = ROW_HOVER if row_data.get("hovered") else SURFACE
        frame = row_data.get("frame")
        content = row_data.get("content")
        name_field = row_data.get("name_field")
        name_entry = row_data.get("name_entry")
        bm_entry = row_data.get("bm_entry")
        delete = row_data.get("delete")
        confidence = float(row_data.get("confidence", 0.0))
        if isinstance(frame, tk.Frame):
            frame.configure(bg=background)
        if isinstance(content, tk.Frame):
            content.configure(bg=background)
        if isinstance(name_field, tk.Frame) and isinstance(name_entry, tk.Entry):
            if name_entry.focus_get() is not name_entry:
                name_field.configure(
                    bg=background,
                    highlightthickness=1 if confidence < 55 else 0,
                    highlightbackground=DANGER if confidence < 55 else background,
                )
                name_entry.configure(bg=background)
        if isinstance(bm_entry, tk.Entry) and bm_entry.focus_get() is not bm_entry:
            bm_entry.configure(
                bg=background,
                fg=MUTED,
                highlightthickness=0,
                highlightbackground=background,
            )
        if isinstance(delete, StyledDeleteButton):
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

    def _set_result_row_hover(
        self, row_data: dict[str, object], hovered: bool
    ) -> None:
        if bool(row_data.get("hovered")) == hovered:
            return
        row_data["hovered"] = hovered
        self._update_result_row_appearance(row_data)

    def _finish_result_row_leave(self, row_data: dict[str, object]) -> None:
        frame = row_data.get("frame")
        if not isinstance(frame, tk.Frame) or not frame.winfo_exists():
            return
        try:
            pointed = frame.winfo_containing(
                frame.winfo_pointerx(), frame.winfo_pointery()
            )
        except tk.TclError:
            pointed = None
        current = pointed
        while current is not None:
            if current is frame:
                return
            current = getattr(current, "master", None)
        self._set_result_row_hover(row_data, False)

    @staticmethod
    def _normalized_participant_name(name: str) -> str:
        return nickname_lookup_key(name)

    def _on_result_name_changed(
        self, row_data: dict[str, object]
    ) -> None:
        name_var = row_data.get("name")
        if isinstance(name_var, tk.StringVar):
            initial_name = clean_nickname(str(row_data.get("initial_name", "")))
            current_name = clean_nickname(name_var.get())
            row_data["name_edited"] = current_name != initial_name
        self._update_result_badges(row_data)

    def _existing_participant_bm(self, name: str) -> float | None:
        normalized = self._normalized_participant_name(name)
        if not normalized:
            return None
        for participant_row in self.owner.rows:
            existing_name = participant_row.get("name")
            existing_bm = participant_row.get("bm")
            if isinstance(existing_name, tk.StringVar):
                if self._normalized_participant_name(existing_name.get()) == normalized:
                    if not isinstance(existing_bm, tk.StringVar):
                        return None
                    try:
                        return parse_bm(existing_bm.get())
                    except ValueError:
                        return None
        return None

    def _update_result_badges(self, row_data: dict[str, object]) -> None:
        name_var = row_data.get("name")
        bm_var = row_data.get("bm")
        new_badge = row_data.get("new_badge")
        update_badge = row_data.get("update_badge")
        if (
            not isinstance(name_var, tk.StringVar)
            or not isinstance(bm_var, tk.StringVar)
            or not isinstance(new_badge, tk.Label)
            or not isinstance(update_badge, tk.Label)
        ):
            return
        normalized_name = self._normalized_participant_name(name_var.get())
        existing_bm = self._existing_participant_bm(name_var.get())
        is_new = bool(normalized_name) and existing_bm is None
        try:
            imported_bm = parse_bm(bm_var.get())
        except ValueError:
            imported_bm = math.nan
        is_updated = (
            not is_new
            and existing_bm is not None
            and math.isfinite(imported_bm)
            and not math.isclose(imported_bm, existing_bm)
        )

        for badge, visible in (
            (new_badge, is_new),
            (update_badge, is_updated),
        ):
            if visible and not badge.winfo_manager():
                badge.pack(
                    side="right",
                    padx=(self._px(6), self._px(6)),
                    pady=self._px(5),
                )
            elif not visible and badge.winfo_manager():
                badge.pack_forget()

    def _delete_row(self, row_data: dict[str, object]) -> None:
        frame = row_data.get("frame")
        if isinstance(frame, tk.Widget):
            frame.destroy()
        self.rows.remove(row_data)
        self.status_var.set(f"· {len(self.rows)}" if self.rows else "")
        self.action_button.configure(state="normal" if self.rows else "disabled")

    def _apply(self) -> None:
        imported: list[Participant] = []
        correction_updates: list[tuple[str, str]] = []
        for row in self.rows:
            name_var = row.get("name")
            bm_var = row.get("bm")
            if not isinstance(name_var, tk.StringVar) or not isinstance(
                bm_var, tk.StringVar
            ):
                continue
            name = " ".join(name_var.get().strip().split())
            try:
                bm = int(bm_var.get().replace(" ", ""))
            except ValueError:
                bm = -1
            if not name or bm < 0:
                messagebox.showwarning(
                    APP_NAME, "Проверьте имя и БМ в результатах.", parent=self
                )
                return
            imported.append(Participant(name[:40], False, float(bm)))
            recognized_name = clean_nickname(
                str(row.get("recognized_name", ""))
            )
            if bool(row.get("name_edited")) and recognized_name:
                correction_updates.append((recognized_name, name[:40]))
        if correction_updates:
            try:
                self.owner.owner.remember_nickname_corrections(
                    correction_updates
                )
            except OSError as error:
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось сохранить замену ника:\n{error}",
                    parent=self,
                )
                return
        if imported:
            self.owner.apply_import(imported)
        self._close()

    def _clear_content(self) -> None:
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._update_scrollbar_visibility)

    def _resize_content(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.content_window, width=event.width)
        self.after_idle(self._update_scrollbar_visibility)

    def _update_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.canvas.winfo_height() + 1
        if should_show and not self._scrollbar_visible:
            self.scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
        elif not should_show and self._scrollbar_visible:
            self.canvas.yview_moveto(0.0)
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _start_clipboard_watch(self) -> None:
        if self._clipboard_watch_after_id is not None:
            return
        self._clipboard_was_foreground = is_foreground_window(self)
        self._clipboard_sequence_before_blur = clipboard_sequence_number()
        self._clipboard_watch_after_id = self.after(
            180, self._poll_clipboard_history
        )

    def _poll_clipboard_history(self) -> None:
        self._clipboard_watch_after_id = None
        if not self.winfo_exists():
            return
        foreground = is_foreground_window(self)
        sequence = clipboard_sequence_number()
        if not foreground and self._clipboard_was_foreground:
            self._clipboard_sequence_before_blur = sequence
        elif foreground and not self._clipboard_was_foreground:
            clipboard_changed = (
                sequence
                and sequence != self._clipboard_sequence_before_blur
                and sequence != self._last_imported_clipboard_sequence
            )
            if clipboard_changed:
                self.after(
                    60,
                    lambda revision=sequence: self._paste_clipboard_history(
                        revision
                    ),
                )
        self._clipboard_was_foreground = foreground
        self._clipboard_watch_after_id = self.after(
            180, self._poll_clipboard_history
        )

    def _paste_clipboard_history(self, expected_sequence: int) -> None:
        if (
            self.busy
            or expected_sequence == self._last_imported_clipboard_sequence
            or clipboard_sequence_number() != expected_sequence
        ):
            return
        try:
            image = clipboard_image()
        except OcrError:
            # Win+V can also be used for text; that should remain a normal
            # Windows paste and must not produce an image warning here.
            return
        self.screenshots.append(image.copy())
        self._last_imported_clipboard_sequence = expected_sequence
        self._show_screenshot_view()

    def _close(self) -> None:
        self.loading_text.stop()
        if self._clipboard_watch_after_id is not None:
            try:
                self.after_cancel(self._clipboard_watch_after_id)
            except tk.TclError:
                pass
            self._clipboard_watch_after_id = None
        if getattr(self.owner, "import_dialog", None) is self:
            self.owner.import_dialog = None
        self.destroy()

    def _center_on_application(self) -> None:
        self.update_idletasks()
        application = self.owner.winfo_toplevel()
        frame_offset_x = self.winfo_rootx() - self.winfo_x()
        frame_offset_y = self.winfo_rooty() - self.winfo_y()
        dialog_width = max(self._px(760), self.winfo_width())
        dialog_height = max(self._px(660), self.winfo_height())
        x = application.winfo_rootx() + (
            application.winfo_width() - dialog_width
        ) // 2 - frame_offset_x
        y = application.winfo_rooty() + (
            application.winfo_height() - dialog_height
        ) // 2 - frame_offset_y
        self._open_geometry = (
            f"{dialog_width}x{dialog_height}+{max(0, x)}+{max(0, y)}"
        )
        if os.name == "nt":
            self.geometry(f"{dialog_width}x{dialog_height}-32000-32000")
        else:
            self.geometry(self._open_geometry)
        apply_dark_title_bar(self)
        self.deiconify()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.update_idletasks()
        apply_dark_title_bar(self)
        self.after(30, self._finish_open)

    def _finish_open(self) -> None:
        apply_dark_title_bar(self)
        self.geometry(self._open_geometry)
        self.update_idletasks()
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()
        self.after(120, self._start_clipboard_watch)


class ParticipantsPanel(tk.Frame):
    SELECTION_UPDATE_DELAY_MS = 90

    def __init__(self, parent: tk.Misc, owner: "WheelApp") -> None:
        super().__init__(parent, bg=PANEL_BACKGROUND)
        self.owner = owner
        self.ui_scale = float(getattr(owner, "ui_scale", widget_ui_scale(parent)))
        self.rows: list[dict[str, object]] = []
        self.import_dialog: ScreenshotImportDialog | None = None
        self.history_dialog: DrawHistoryDialog | None = None
        self._auto_save_ready = False
        self._auto_save_after_id: str | None = None
        self._save_pending = False
        self._last_save_error = ""
        self._syncing_select_all = False
        self._bulk_selection = False
        self._clear_focus_after_restore = False
        influence = owner.bm_influence_percent
        influence_text = (
            str(int(influence))
            if float(influence).is_integer()
            else f"{influence:.2f}".rstrip("0").rstrip(".")
        )
        self.influence_var = tk.StringVar(value=influence_text)

        self._build_ui()
        for participant in sort_participants_by_bm(owner.participants):
            self._add_row(
                participant.name,
                participant.enabled,
                participant.bm,
                scroll_to_end=False,
            )
        self.influence_var.trace_add("write", self._on_text_value_changed)
        self.influence_entry.bind("<FocusIn>", self._on_entry_focus_in, add="+")
        self.influence_entry.bind("<FocusOut>", self._on_entry_focus_out, add="+")
        self._click_binding_id = self.owner.bind_all(
            "<Button-1>", self._clear_entry_focus_on_click, add="+"
        )
        self._return_binding_id = self.owner.bind_all(
            "<Return>", self._clear_entry_focus_on_enter, add="+"
        )
        self._unmap_binding_id = self.owner.bind(
            "<Unmap>", self._on_owner_unmap, add="+"
        )
        self._map_binding_id = self.owner.bind(
            "<Map>", self._on_owner_map, add="+"
        )
        self._auto_save_ready = True
        self.after_idle(lambda: self.canvas.yview_moveto(0.0))

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _build_ui(self) -> None:
        heading = tk.Frame(self, bg=PANEL_BACKGROUND)
        heading.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(18), self._px(10)),
        )

        tk.Label(
            heading,
            text="УЧАСТНИКИ",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left", anchor="w")
        self.guild_count_label = tk.Label(
            heading,
            text="· 0",
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 14),
        )
        self.guild_count_label.pack(
            side="left", padx=(self._px(7), 0), pady=(self._px(2), 0)
        )

        self.import_button = self._button(
            heading, "Из буфера", self._open_import, SURFACE_LIGHT, TEXT
        )
        self.import_button.pack(side="right")
        self.add_button = self._button(
            heading, "+  Добавить", self._add_empty_row, SURFACE_LIGHT, TEXT
        )
        self.add_button.pack(side="right", padx=(0, self._px(8)))
        self.history_separator = tk.Frame(
            heading,
            bg=BORDER,
            width=self._px(1),
        )
        self.history_separator.pack(
            side="right",
            fill="y",
            padx=self._px(12),
            pady=self._px(2),
        )
        self.history_button = self._button(
            heading,
            "История",
            self._open_history,
            SURFACE_LIGHT,
            TEXT,
        )
        self.history_button.pack(side="right")

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(fill="both", expand=True, padx=self._px(24))

        columns_header = tk.Frame(
            list_shell, bg=SURFACE, height=self._px(27)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        columns_header.grid_columnconfigure(0, weight=1, uniform="headers")
        columns_header.grid_columnconfigure(1, weight=1, uniform="headers")
        for column in range(2):
            column_header = tk.Frame(columns_header, bg=SURFACE)
            column_header.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=self._px(6),
            )
            tk.Label(
                column_header,
                text="ИГРОК",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            ).pack(
                side="left",
                padx=(self._px(53), 0),
                pady=(self._px(6), self._px(4)),
            )
            tk.Label(
                column_header,
                text="БМ",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            ).pack(
                side="right",
                padx=(0, self._px(48)),
                pady=(self._px(6), self._px(4)),
            )
        tk.Frame(list_shell, bg="#343B36", height=self._px(1)).pack(fill="x")

        list_body = tk.Frame(list_shell, bg=SURFACE)
        list_body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            list_body, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            list_body, orient="vertical", command=self.canvas.yview
        )
        self._scrollbar_visible = False
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_frame.grid_columnconfigure(0, weight=1, uniform="participants")
        self.rows_frame.grid_columnconfigure(1, weight=1, uniform="participants")
        self.rows_window = self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)

        influence_row = tk.Frame(self, bg=PANEL_BACKGROUND)
        influence_row.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(11), self._px(17)),
        )

        selection_controls = tk.Frame(influence_row, bg=PANEL_BACKGROUND)
        selection_controls.pack(side="left")
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_check = StyledCheckbutton(
            selection_controls,
            variable=self.select_all_var,
            background=PANEL_BACKGROUND,
        )
        self.select_all_check.pack(side="left")
        select_all_label = tk.Label(
            selection_controls,
            text="Выбрать всех",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        select_all_label.pack(side="left", padx=(self._px(8), 0))
        select_all_label.bind("<Button-1>", self._toggle_select_all_label)
        self.clear_selection_button = tk.Label(
            selection_controls,
            text="Убрать выделение",
            bg=PANEL_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 10),
            cursor="hand2",
            padx=self._px(2),
            pady=self._px(5),
        )
        self.clear_selection_button.pack(
            side="left", padx=(self._px(16), 0)
        )
        self.clear_selection_button.bind(
            "<Button-1>", lambda _event: self._clear_selection()
        )
        self.clear_selection_button.bind(
            "<Enter>", lambda _event: self.clear_selection_button.configure(fg=TEXT)
        )
        self.clear_selection_button.bind(
            "<Leave>", lambda _event: self.clear_selection_button.configure(fg=MUTED)
        )
        self.select_all_var.trace_add("write", self._on_select_all_changed)

        bm_controls = tk.Frame(influence_row, bg=PANEL_BACKGROUND)
        bm_controls.pack(side="right", fill="y")
        tk.Frame(
            bm_controls,
            bg=BORDER,
            width=self._px(1),
        ).pack(
            side="left",
            fill="y",
            padx=(0, self._px(18)),
            pady=self._px(2),
        )

        influence_label = tk.Label(
            bm_controls,
            text="% влияния БМ на вероятность",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
        )
        self.influence_entry = tk.Entry(
            bm_controls,
            textvariable=self.influence_var,
            width=7,
            justify="center",
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=INPUT_BACKGROUND,
            disabledforeground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(self.influence_entry)
        self.influence_entry.pack(side="right", ipady=self._px(6))
        influence_label.pack(side="right", padx=(0, self._px(10)))

    @staticmethod
    def _button(
        parent: tk.Misc,
        text: str,
        command: object,
        background: str,
        foreground: str,
    ) -> tk.Button:
        if background == ACCENT:
            hover_background = ACCENT_HOVER
            normal_border = ACCENT_DARK
            hover_border = ACCENT_HOVER
        elif background in (SURFACE, SURFACE_LIGHT):
            hover_background = BUTTON_HOVER
            normal_border = BUTTON_BORDER
            hover_border = BUTTON_HOVER_BORDER
        else:
            hover_background = SURFACE_LIGHT
            normal_border = background
            hover_border = BUTTON_BORDER

        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=hover_background,
            activeforeground=TEXT,
            disabledforeground=DISABLED_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=normal_border,
            highlightcolor=normal_border,
            cursor="hand2",
            font=("Segoe UI Semibold", 10),
            padx=scaled_px(parent, 15),
            pady=scaled_px(parent, 8),
        )

        def enter(_event: tk.Event[tk.Misc]) -> None:
            if str(button.cget("state")) == "normal":
                button.configure(
                    bg=hover_background,
                    highlightbackground=hover_border,
                    highlightcolor=hover_border,
                )

        def leave(_event: tk.Event[tk.Misc]) -> None:
            if str(button.cget("state")) == "normal":
                button.configure(
                    bg=background,
                    highlightbackground=normal_border,
                    highlightcolor=normal_border,
                )

        button.bind("<Enter>", enter)
        button.bind("<Leave>", leave)
        return button

    def _add_row(
        self,
        name: str = "",
        enabled: bool = True,
        bm: float = 0.0,
        scroll_to_end: bool = True,
    ) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        content = tk.Frame(
            row, bg=SURFACE, padx=self._px(10), pady=self._px(1)
        )
        content.pack(fill="x")
        separator = tk.Frame(row, bg="#343B36", height=self._px(1))
        separator.pack(fill="x", padx=self._px(8))

        selection_strip = tk.Frame(
            content,
            bg=ACCENT if enabled else SURFACE,
            width=self._px(3),
        )
        selection_strip.pack(
            side="left", fill="y", padx=(0, self._px(7))
        )
        selection_strip.pack_propagate(False)

        enabled_var = tk.BooleanVar(value=enabled)
        check = StyledCheckbutton(
            content,
            variable=enabled_var,
            background=SURFACE,
        )
        check.pack(side="left", padx=(0, self._px(10)))

        name_var = tk.StringVar(value=name)
        entry = tk.Entry(
            content,
            textvariable=name_var,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=SURFACE,
            disabledforeground=TEXT,
            relief="flat",
            font=("Segoe UI", 11),
            highlightthickness=0,
            highlightbackground=SURFACE,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(entry)
        entry.pack(
            side="left", fill="x", expand=True, ipady=self._px(2)
        )

        bm_text = format_bm(bm)
        bm_var = tk.StringVar(value=bm_text)
        bm_entry = tk.Entry(
            content,
            textvariable=bm_var,
            width=9,
            justify="right",
            bg=SURFACE,
            fg=MUTED,
            insertbackground=TEXT,
            disabledbackground=SURFACE,
            disabledforeground=MUTED,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=0,
            highlightbackground=SURFACE,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(bm_entry)
        bm_entry.pack(
            side="left",
            padx=(self._px(12), 0),
            ipady=self._px(3),
        )

        row_data: dict[str, object] = {
            "frame": row,
            "content": content,
            "name": name_var,
            "name_entry": entry,
            "enabled": enabled_var,
            "bm": bm_var,
            "bm_entry": bm_entry,
            "check": check,
            "selection_strip": selection_strip,
            "separator": separator,
            "hovered": False,
        }
        delete = StyledDeleteButton(
            content,
            command=lambda data=row_data: self._delete_row(data),
            background=SURFACE,
        )
        row_data["delete"] = delete
        delete.pack(side="right", padx=(self._px(8), 0))
        self.rows.append(row_data)
        self._place_row(row_data, len(self.rows) - 1)
        self._refresh_select_all_state()
        self._update_guild_count()

        name_var.trace_add("write", self._on_text_value_changed)
        bm_var.trace_add("write", self._on_text_value_changed)
        enabled_var.trace_add("write", self._on_toggle_value_changed)
        enabled_var.trace_add(
            "write", lambda *_args, data=row_data: self._update_row_selection(data)
        )
        self._update_row_selection(row_data)
        entry.bind("<FocusIn>", self._on_entry_focus_in, add="+")
        entry.bind("<FocusOut>", self._on_entry_focus_out, add="+")
        bm_entry.bind("<FocusIn>", self._on_entry_focus_in, add="+")
        bm_entry.bind("<FocusOut>", self._on_entry_focus_out, add="+")

        hover_widgets = (row, content, selection_strip, check, entry, bm_entry, delete)
        for widget in hover_widgets:
            widget.bind(
                "<Enter>",
                lambda _event, data=row_data: self._set_row_hover(data, True),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event, data=row_data: self.after_idle(
                    lambda item=data: self._finish_row_leave(item)
                ),
                add="+",
            )
            widget.bind("<MouseWheel>", self._scroll)

        if not name:
            entry.focus_set()
        if scroll_to_end:
            self.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def _add_empty_row(self) -> None:
        self._add_row()

    def _delete_row(self, row_data: dict[str, object]) -> None:
        frame = row_data["frame"]
        if isinstance(frame, tk.Widget):
            frame.destroy()
        self.rows.remove(row_data)
        self._reflow_rows()
        self._refresh_select_all_state()
        self._update_guild_count()
        self._schedule_auto_save(0)

    def _place_row(self, row_data: dict[str, object], index: int) -> None:
        frame = row_data.get("frame")
        if not isinstance(frame, tk.Widget):
            return
        frame.grid(
            row=index // 2,
            column=index % 2,
            sticky="ew",
            padx=(self._px(6), self._px(3))
            if index % 2 == 0
            else (self._px(3), self._px(6)),
        )

    def _reflow_rows(self) -> None:
        for index, row_data in enumerate(self.rows):
            self._place_row(row_data, index)

    def _sort_rows_by_bm(self) -> None:
        """Sort rows by BM and lay them out left-to-right, then top-to-bottom."""

        def row_key(row_data: dict[str, object]) -> tuple[int, float]:
            name_var = row_data.get("name")
            bm_var = row_data.get("bm")
            name = name_var.get().strip() if isinstance(name_var, tk.StringVar) else ""
            try:
                bm = parse_bm(bm_var.get()) if isinstance(bm_var, tk.StringVar) else 0.0
            except ValueError:
                return (1, 0.0)
            if not name or not math.isfinite(bm) or bm < 0:
                return (1, 0.0)
            return (0, -bm)

        ordered_rows = sorted(self.rows, key=row_key)
        if ordered_rows == self.rows:
            return
        self.rows[:] = ordered_rows
        for row_data in self.rows:
            frame = row_data.get("frame")
            if isinstance(frame, tk.Widget):
                frame.grid_forget()
        self._reflow_rows()

    def _update_guild_count(self) -> None:
        self.guild_count_label.configure(text=f"· {len(self.rows)}")

    def _update_row_selection(self, row_data: dict[str, object]) -> None:
        enabled_var = row_data.get("enabled")
        frame = row_data.get("frame")
        content = row_data.get("content")
        strip = row_data.get("selection_strip")
        check = row_data.get("check")
        name_entry = row_data.get("name_entry")
        bm_entry = row_data.get("bm_entry")
        delete = row_data.get("delete")
        if not isinstance(enabled_var, tk.BooleanVar):
            return
        hovered = bool(row_data.get("hovered"))
        if enabled_var.get():
            background = ROW_SELECTED_HOVER if hovered else ROW_SELECTED
        else:
            background = ROW_HOVER if hovered else SURFACE
        if isinstance(frame, tk.Frame):
            frame.configure(bg=background)
        if isinstance(content, tk.Frame):
            content.configure(bg=background)
        if isinstance(strip, tk.Frame):
            strip.configure(bg=ACCENT if enabled_var.get() else background)
        if isinstance(check, StyledCheckbutton):
            check.configure(bg=background)
        for entry in (name_entry, bm_entry):
            if isinstance(entry, tk.Entry):
                normal_foreground = MUTED if entry is bm_entry else TEXT
                entry.configure(
                    disabledbackground=background,
                    disabledforeground=normal_foreground,
                )
                if entry.focus_get() is not entry:
                    entry.configure(
                        bg=background,
                        fg=normal_foreground,
                        highlightthickness=0,
                        highlightbackground=background,
                    )
        if isinstance(delete, StyledDeleteButton):
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

    def _set_row_hover(
        self, row_data: dict[str, object], hovered: bool
    ) -> None:
        if bool(row_data.get("hovered")) == hovered:
            return
        row_data["hovered"] = hovered
        self._update_row_selection(row_data)

    def _finish_row_leave(self, row_data: dict[str, object]) -> None:
        frame = row_data.get("frame")
        if not isinstance(frame, tk.Frame) or not frame.winfo_exists():
            return
        try:
            pointed = frame.winfo_containing(
                frame.winfo_pointerx(), frame.winfo_pointery()
            )
        except tk.TclError:
            pointed = None
        current = pointed
        while current is not None:
            if current is frame:
                return
            current = getattr(current, "master", None)
        self._set_row_hover(row_data, False)

    def _open_import(self) -> None:
        if self.import_dialog is not None and self.import_dialog.winfo_exists():
            self.import_dialog.deiconify()
            self.import_dialog.lift()
            self.import_dialog.focus_force()
            return
        self.import_dialog = ScreenshotImportDialog(self)

    def _open_history(self) -> None:
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog.refresh()
            self.history_dialog.deiconify()
            self.history_dialog.lift()
            self.history_dialog.focus_force()
            return
        self.history_dialog = DrawHistoryDialog(self)

    def refresh_history_dialog(self) -> None:
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog.refresh()

    def apply_import(self, participants: list[Participant]) -> None:
        existing: dict[str, dict[str, object]] = {}
        for row in self.rows:
            name_var = row.get("name")
            if isinstance(name_var, tk.StringVar):
                existing[name_var.get().strip().casefold()] = row

        for participant in participants:
            row = existing.get(participant.name.casefold())
            if row is None:
                self._add_row(participant.name, False, participant.bm)
                continue
            bm_var = row.get("bm")
            if isinstance(bm_var, tk.StringVar):
                bm_var.set(format_bm(participant.bm))
        self._schedule_auto_save(0)

    def _on_text_value_changed(self, *_args: object) -> None:
        self._schedule_auto_save(250)

    def _on_toggle_value_changed(self, *_args: object) -> None:
        if self._bulk_selection:
            return
        self._release_entry_focus()
        self._refresh_select_all_state()
        self._schedule_auto_save(self.SELECTION_UPDATE_DELAY_MS)

    def _on_select_all_changed(self, *_args: object) -> None:
        if self._syncing_select_all:
            return
        self._set_all_enabled(self.select_all_var.get())

    def _toggle_select_all_label(self, _event: tk.Event[tk.Misc]) -> str:
        if str(self.select_all_check.cget("state")) != "disabled":
            self.select_all_var.set(not self.select_all_var.get())
        return "break"

    def _clear_selection(self) -> None:
        if self.owner.spinning:
            return
        self._set_all_enabled(False)

    def _set_all_enabled(self, enabled: bool) -> None:
        self._release_entry_focus()
        self._bulk_selection = True
        try:
            for row in self.rows:
                enabled_var = row.get("enabled")
                if isinstance(enabled_var, tk.BooleanVar):
                    enabled_var.set(enabled)
        finally:
            self._bulk_selection = False
        self._refresh_select_all_state()
        self._schedule_auto_save(self.SELECTION_UPDATE_DELAY_MS)

    def _refresh_select_all_state(self) -> None:
        enabled_values = [
            enabled_var.get()
            for row in self.rows
            if isinstance((enabled_var := row.get("enabled")), tk.BooleanVar)
        ]
        all_selected = bool(enabled_values) and all(enabled_values)
        if self.select_all_var.get() == all_selected:
            return
        self._syncing_select_all = True
        try:
            self.select_all_var.set(all_selected)
        finally:
            self._syncing_select_all = False

    def _on_entry_focus_in(self, event: tk.Event[tk.Misc]) -> None:
        if not isinstance(event.widget, tk.Entry):
            return
        event.widget.configure(
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER_LIGHT,
            highlightcolor=BORDER_LIGHT,
        )

    def _on_entry_focus_out(self, event: tk.Event[tk.Misc]) -> None:
        entry = event.widget
        if isinstance(entry, tk.Entry):
            for row in self.rows:
                if row.get("bm_entry") is entry:
                    bm_var = row.get("bm")
                    if isinstance(bm_var, tk.StringVar):
                        try:
                            bm_var.set(format_bm(parse_bm(bm_var.get())))
                        except ValueError:
                            pass
                if row.get("bm_entry") is entry or row.get("name_entry") is entry:
                    self.after_idle(
                        lambda data=row: self._update_row_selection(data)
                    )
                    break
        self._schedule_auto_save(0)

    def _clear_entry_focus_on_enter(self, event: tk.Event[tk.Misc]) -> str | None:
        if not isinstance(event.widget, tk.Entry):
            return None
        if self._is_panel_widget(event.widget):
            self._schedule_auto_save(0)
        event.widget.winfo_toplevel().focus_set()
        return "break"

    def _clear_entry_focus_on_click(self, event: tk.Event[tk.Misc]) -> None:
        try:
            focused = self.owner.focus_get()
        except (KeyError, tk.TclError):
            return
        if not isinstance(focused, tk.Entry) or event.widget is focused:
            return
        if self._is_panel_widget(focused):
            self._schedule_auto_save(0)
        if isinstance(event.widget, tk.Entry):
            return

        def move_focus() -> None:
            try:
                if event.widget.winfo_exists():
                    event.widget.focus_set()
            except (KeyError, tk.TclError):
                pass

        self.after_idle(move_focus)

    def _release_entry_focus(self) -> None:
        try:
            focused = self.owner.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if isinstance(focused, tk.Entry) and self._is_panel_widget(focused):
            self._schedule_auto_save(0)
        try:
            self.owner.focus_set()
        except tk.TclError:
            pass

    def _on_owner_unmap(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.owner:
            return
        self._clear_focus_after_restore = True
        self._release_entry_focus()

    def _on_owner_map(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.owner or not self._clear_focus_after_restore:
            return
        self._clear_focus_after_restore = False
        self.after_idle(self._release_entry_focus)

    def _is_panel_widget(self, widget: tk.Misc) -> bool:
        current: tk.Misc | None = widget
        while current is not None:
            if current is self:
                return True
            current = getattr(current, "master", None)
        return False

    def _schedule_auto_save(self, delay_ms: int) -> None:
        if not self._auto_save_ready:
            return
        if self.owner.spinning:
            self._save_pending = True
            return
        if self._auto_save_after_id is not None:
            try:
                self.after_cancel(self._auto_save_after_id)
            except tk.TclError:
                pass
        self._auto_save_after_id = self.after(delay_ms, self._perform_auto_save)

    def _set_entry_valid(self, entry: tk.Entry, valid: bool) -> None:
        is_influence = entry is self.influence_entry
        focused = entry.focus_get() is entry
        color = BORDER if valid else DANGER
        focus_color = BORDER_LIGHT if valid else "#C46B68"
        entry.configure(
            highlightthickness=1 if is_influence or focused or not valid else 0,
            highlightbackground=color,
            highlightcolor=focus_color,
        )

    def _perform_auto_save(self) -> None:
        self._auto_save_after_id = None
        if self.owner.spinning:
            self._save_pending = True
            return

        try:
            influence_percent = float(
                self.influence_var.get().strip().replace(",", ".")
            )
        except ValueError:
            influence_percent = -1.0
        influence_valid = (
            math.isfinite(influence_percent)
            and 0 <= influence_percent <= 100
        )
        self._set_entry_valid(self.influence_entry, influence_valid)
        if not influence_valid:
            return

        participants: list[Participant] = []
        rows_valid = True
        for row in self.rows:
            name_var = row.get("name")
            enabled_var = row.get("enabled")
            bm_var = row.get("bm")
            bm_entry = row.get("bm_entry")
            if (
                not isinstance(name_var, tk.StringVar)
                or not isinstance(enabled_var, tk.BooleanVar)
                or not isinstance(bm_var, tk.StringVar)
                or not isinstance(bm_entry, tk.Entry)
            ):
                continue
            name = " ".join(name_var.get().strip().split())
            try:
                bm = parse_bm(bm_var.get())
            except ValueError:
                bm = -1.0
            bm_valid = math.isfinite(bm) and bm >= 0
            self._set_entry_valid(bm_entry, bm_valid)
            if not bm_valid:
                rows_valid = False
                continue
            if name:
                participants.append(Participant(name[:40], enabled_var.get(), bm))

        if not rows_valid:
            return

        participants = sort_participants_by_bm(participants)
        try:
            focused_widget = self.owner.focus_get()
        except (KeyError, tk.TclError):
            focused_widget = None
        editing_bm = any(
            row.get("bm_entry") is focused_widget for row in self.rows
        )
        if not editing_bm:
            self._sort_rows_by_bm()

        if (
            participants == self.owner.participants
            and math.isclose(influence_percent, self.owner.bm_influence_percent)
        ):
            self._save_pending = False
            return

        try:
            self.owner.set_participants(participants, influence_percent)
        except OSError as error:
            error_text = str(error)
            if error_text != self._last_save_error:
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось сохранить список:\n{error}",
                    parent=self,
                )
                self._last_save_error = error_text
            return

        self._last_save_error = ""
        self._save_pending = False

    def flush_auto_save(self) -> None:
        if self._auto_save_after_id is None and not self._save_pending:
            return
        if self._auto_save_after_id is not None:
            try:
                self.after_cancel(self._auto_save_after_id)
            except tk.TclError:
                pass
            self._auto_save_after_id = None
        self._perform_auto_save()

    def set_editing_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"

        def update_widgets(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if isinstance(
                    child,
                    (
                        tk.Button,
                        tk.Checkbutton,
                        tk.Entry,
                        StyledCheckbutton,
                        StyledDeleteButton,
                    ),
                ):
                    child.configure(state=state)
                update_widgets(child)

        update_widgets(self)
        if enabled and self._save_pending:
            self._schedule_auto_save(0)

    def destroy(self) -> None:
        if self._auto_save_after_id is not None:
            try:
                self.after_cancel(self._auto_save_after_id)
            except tk.TclError:
                pass
            self._auto_save_after_id = None
        if self.import_dialog is not None and self.import_dialog.winfo_exists():
            self.import_dialog._close()
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog._close()
        try:
            self.owner.unbind_all("<Button-1>")
            self.owner.unbind_all("<Return>")
            self.owner.unbind("<Unmap>", self._unmap_binding_id)
            self.owner.unbind("<Map>", self._map_binding_id)
        except tk.TclError:
            pass
        super().destroy()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._update_scrollbar_visibility)

    def _resize_rows(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.rows_window, width=event.width)
        self.after_idle(self._update_scrollbar_visibility)

    def _update_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.canvas.winfo_height() + 1
        if should_show and not self._scrollbar_visible:
            self.scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
        elif not should_show and self._scrollbar_visible:
            self.canvas.yview_moveto(0.0)
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"


class WheelApp(tk.Tk):
    LEFT_PANEL_WIDTH = 820
    CANVAS_SIZE = 780
    CANVAS_HEIGHT = 740
    CENTER_X = 390
    CENTER_Y = 376
    RADIUS = 352
    CENTER_MEDALLION_RADIUS = 70
    GUILD_ICON_SIZE = 112
    LABEL_RADIUS_RATIO = 0.67
    DENSE_LABEL_RADIUS_RATIO = 0.74
    ANTIALIAS_SCALE = 4
    DISC_ANTIALIAS_SCALE = 4
    SPIN_DURATION_SECONDS = 4.8
    MULTI_SPIN_DURATION_SECONDS = 3.6
    MULTI_WINNER_HOLD_SECONDS = 0.65
    SECTOR_TRANSITION_SECONDS = 0.70
    VIDEO_FPS = 24
    VIDEO_CAPTURE_HEIGHT = 912
    VIDEO_FINAL_HOLD_SECONDS = 2.0
    PRIZE_UI_MAX_CARD_WIDTH = 465

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.ui_scale = self._calculate_ui_scale()
        self._native_tk_scaling = 1.0
        try:
            self._native_tk_scaling = float(self.tk.call("tk", "scaling"))
            self.tk.call(
                "tk", "scaling", self._native_tk_scaling * self.ui_scale
            )
        except (tk.TclError, TypeError, ValueError):
            pass
        self._update_display_metrics()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.store = ParticipantStore()
        self.draw_log_store = DrawLogStore()
        self.participants = sort_participants_by_bm(self.store.load())
        self.bm_influence_percent = self.store.bm_influence_percent
        self.nickname_corrections = list(self.store.nickname_corrections)
        self.rotation = 0.0
        self.spinning = False
        self._winner_index: int | None = None
        self._show_winner_glow = False
        self._roll_slots: list[Participant] | None = None
        self._roll_remaining: list[Participant] = []
        self._roll_probabilities: list[float] | None = None
        self._roll_winners: list[str] = []
        self._roll_target_count = 1
        self._wheel_cache_key: tuple[float, ...] | None = None
        self._wheel_render_queue: queue.Queue[
            tuple[int, tuple[float, ...], Image.Image | None]
        ] = queue.Queue()
        self._wheel_render_generation = 0
        self._wheel_render_jobs = 0
        self._wheel_render_polling = False
        self._wheel_pending_key: tuple[float, ...] | None = None
        self._wheel_disc_array: np.ndarray | None = None
        self._video_frames: list[RecordedWheelFrame] = []
        self._video_generation = 0
        self._video_queue: queue.Queue[tuple[int, bytes | Exception]] = queue.Queue()
        self._video_polling = False
        self._video_jobs = 0
        self._roll_video_bytes: bytes | None = None
        self._roll_prize_image: Image.Image | None = None
        self._roll_prize_quantity = 1
        self._video_preparation_failed = False
        self._reward_ocr_generation = 0
        self._reward_ocr_queue: queue.Queue[tuple[int, str | Exception]] = (
            queue.Queue()
        )
        self._reward_ocr_jobs = 0
        self._reward_ocr_polling = False
        self._reward_ocr_pending = False
        self._pending_draw_results: list[DrawResult] = []
        self._roll_logged = False
        self._monitor_check_after_id: str | None = None
        self._show_main_after_id: str | None = None
        self._finish_show_after_id: str | None = None
        self._rebuilding_ui = False
        self.button_process_text = AnimatedEllipsis(self)

        self.title(APP_NAME)
        apply_window_icon(self, default=True)
        self.geometry(f"{self._px(1280)}x{self._px(760)}")
        self.minsize(self._px(1050), self._px(650))
        self.resizable(True, True)
        self.configure(bg=BACKGROUND)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        keep_dark_title_bar(self)

        self._configure_styles()
        self._build_ui()
        self._draw_wheel()
        self.bind("<Configure>", self._on_window_configure, add="+")
        self._show_main_after_id = self.after_idle(self._show_main_window)

    def destroy(self) -> None:
        for attribute in (
            "_monitor_check_after_id",
            "_show_main_after_id",
            "_finish_show_after_id",
        ):
            callback_id = getattr(self, attribute, None)
            if callback_id is None:
                continue
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)
        super().destroy()

    def _calculate_ui_scale(self) -> float:
        width, height = monitor_size_for_window(self)
        return self._scale_for_monitor(width, height)

    @staticmethod
    def _scale_for_monitor(width: int, height: int) -> float:
        width_ratio = width / DESIGN_SCREEN_WIDTH
        height_ratio = height / DESIGN_SCREEN_HEIGHT
        return min(MAX_UI_SCALE, max(MIN_UI_SCALE, min(width_ratio, height_ratio)))

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _update_display_metrics(self) -> None:
        self.display_left_panel_width = self._px(self.LEFT_PANEL_WIDTH)
        self.display_canvas_size = self._px(self.CANVAS_SIZE)
        self.display_canvas_height = self._px(self.CANVAS_HEIGHT)

    def _on_window_configure(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self or self._rebuilding_ui:
            return
        if self._monitor_check_after_id is not None:
            try:
                self.after_cancel(self._monitor_check_after_id)
            except tk.TclError:
                pass
        self._monitor_check_after_id = self.after(180, self._check_monitor_scale)

    def _check_monitor_scale(self) -> None:
        self._monitor_check_after_id = None
        if not self.winfo_exists():
            return
        width, height = monitor_size_for_window(self)
        new_scale = self._scale_for_monitor(width, height)
        if math.isclose(new_scale, self.ui_scale, abs_tol=0.005):
            return

        import_open = (
            hasattr(self, "participants_panel")
            and self.participants_panel.import_dialog is not None
            and self.participants_panel.import_dialog.winfo_exists()
        )
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        editing = (
            isinstance(focused, tk.Entry)
            and hasattr(self, "participants_panel")
            and self.participants_panel._is_panel_widget(focused)
        )
        if self.spinning or self._video_jobs or import_open or editing:
            self._monitor_check_after_id = self.after(
                250, self._check_monitor_scale
            )
            return
        self._rebuild_scaled_ui(new_scale)

    def _rebuild_scaled_ui(self, new_scale: float) -> None:
        if self._rebuilding_ui:
            return
        self._rebuilding_ui = True
        try:
            self.participants_panel.flush_auto_save()
            prize_image = (
                self.prize_card.image.copy()
                if self.prize_card.image is not None
                else None
            )
            prize_locked = self.prize_card.locked
            prize_quantity = self.prize_quantity_control.value()
            prize_quantity_locked = self.prize_quantity_control.locked
            result_text = self.result_var.get()
            result_visible = bool(self.result_actions.winfo_manager())
            save_button_options = {
                option: self.save_result_button.cget(option)
                for option in (
                    "text",
                    "state",
                    "bg",
                    "highlightbackground",
                    "highlightcolor",
                )
            }

            self.button_process_text.stop()
            self.content.destroy()
            if hasattr(self, "_wheel_image"):
                del self._wheel_image

            self.ui_scale = new_scale
            try:
                self.tk.call(
                    "tk",
                    "scaling",
                    self._native_tk_scaling * self.ui_scale,
                )
            except tk.TclError:
                pass
            self._update_display_metrics()
            self.geometry(f"{self._px(1280)}x{self._px(760)}")
            self.minsize(self._px(1050), self._px(650))
            self._configure_styles()
            self._build_ui()

            if prize_image is not None:
                self.prize_card.set_image(prize_image)
            self.prize_card.set_locked(prize_locked)
            self.prize_quantity_control.set_value(prize_quantity)
            self.prize_quantity_control.set_locked(prize_quantity_locked)
            if result_text:
                self._show_winner_result(result_text)
                if result_visible:
                    self._show_result_controls()
                    self.save_result_button.configure(**save_button_options)
            else:
                self._clear_winner_result()
                self._show_spin_controls()
            self._draw_wheel()
            self._maximize_window()
            self.after_idle(self.participants_panel._update_scrollbar_visibility)
            apply_dark_title_bar(self)
        finally:
            self._rebuilding_ui = False

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Vertical.TScrollbar",
            background="#414741",
            troughcolor="#151815",
            bordercolor="#151815",
            lightcolor="#414741",
            darkcolor="#414741",
            arrowcolor=MUTED,
            relief="flat",
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#59615A")],
            lightcolor=[("active", "#59615A")],
            darkcolor=[("active", "#59615A")],
        )

    def _build_ui(self) -> None:
        content = tk.Frame(self, bg=BACKGROUND)
        self.content = content
        content.pack(fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        left_panel = tk.Frame(
            content,
            bg=BACKGROUND,
            width=self.display_left_panel_width,
            highlightthickness=1,
            highlightbackground="#383E39",
        )
        left_panel.grid(row=0, column=0, sticky="ns")
        left_panel.grid_propagate(False)

        header = tk.Frame(left_panel, bg=BACKGROUND, height=self._px(78))
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(18), 0),
        )
        header.pack_propagate(False)

        title_block = tk.Frame(header, bg=BACKGROUND)
        title_block.pack(side="left", anchor="w")
        tk.Label(
            title_block,
            text=APP_NAME,
            bg=BACKGROUND,
            fg="#D9DDD9",
            font=("Segoe UI Semibold", 21),
        ).pack(anchor="w")
        self.count_label = tk.Label(
            title_block,
            bg=BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.count_label.pack(anchor="w", pady=(self._px(2), 0))

        prize_group = tk.Frame(header, bg=BACKGROUND)
        prize_group.pack(side="right", anchor="center")
        self.prize_quantity_control = PrizeQuantityControl(prize_group)
        self.prize_quantity_control.grid(row=0, column=0)
        self.prize_card = PrizeImageCard(
            prize_group,
            max_card_width=self.PRIZE_UI_MAX_CARD_WIDTH,
            on_clear=lambda: self.prize_quantity_control.set_value(1),
        )
        self.prize_card.grid(
            row=0,
            column=1,
            padx=(self._px(4), 0),
        )

        self.wheel_canvas = tk.Canvas(
            left_panel,
            width=self.display_canvas_size,
            height=self.display_canvas_height,
            bg=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.wheel_canvas.pack()

        controls = tk.Frame(left_panel, bg=BACKGROUND)
        controls.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(2), self._px(18)),
        )

        self.result_var = tk.StringVar(value="")
        self.result_slot = tk.Frame(
            controls,
            bg=BACKGROUND,
            height=self._px(64),
        )
        self.result_slot.pack(fill="x", pady=(0, self._px(8)))
        self.result_slot.pack_propagate(False)

        self.result_card = tk.Frame(
            self.result_slot,
            bg=WINNER_BACKGROUND,
            highlightthickness=1,
            highlightbackground=ACCENT,
        )
        self.result_caption = tk.Label(
            self.result_card,
            text="ПОБЕДИТЕЛЬ",
            bg=WINNER_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        )
        self.result_caption.pack(pady=(self._px(5), self._px(1)))
        self.result_divider = tk.Frame(
            self.result_card,
            bg=ACCENT,
            height=self._px(1),
        )
        self.result_divider.pack(fill="x", padx=self._px(260))
        self.result_label = tk.Label(
            self.result_card,
            textvariable=self.result_var,
            bg=WINNER_BACKGROUND,
            fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 18),
            anchor="center",
        )
        self.result_label.pack(
            fill="x", pady=(self._px(1), self._px(4))
        )

        self.action_slot = tk.Frame(controls, bg=BACKGROUND)
        self.action_slot.pack(fill="x")

        self.spin_button = tk.Button(
            self.action_slot,
            text="КРУТИТЬ КОЛЕСО",
            command=self._start_spin,
            bg=CTA_BACKGROUND,
            fg="#F1EEE5",
            activebackground=CTA_PRESSED,
            activeforeground="#F1EEE5",
            disabledforeground="#686E69",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=CTA_BORDER,
            highlightcolor=CTA_BORDER,
            cursor="hand2",
            font=("Segoe UI Semibold", 12),
            pady=self._px(12),
        )
        self.spin_button.pack(fill="x")

        def spin_enter(_event: tk.Event[tk.Misc]) -> None:
            if str(self.spin_button.cget("state")) == "normal":
                self.spin_button.configure(
                    bg=CTA_HOVER,
                    highlightbackground=CTA_HOVER_BORDER,
                    highlightcolor=CTA_HOVER_BORDER,
                )

        def spin_leave(_event: tk.Event[tk.Misc]) -> None:
            if str(self.spin_button.cget("state")) == "normal":
                self.spin_button.configure(
                    bg=CTA_BACKGROUND,
                    highlightbackground=CTA_BORDER,
                    highlightcolor=CTA_BORDER,
                )

        self.spin_button.bind("<Enter>", spin_enter)
        self.spin_button.bind("<Leave>", spin_leave)

        self.result_actions = tk.Frame(self.action_slot, bg=BACKGROUND)
        self.result_actions.grid_columnconfigure(0, weight=1, uniform="roll_actions")
        self.result_actions.grid_columnconfigure(1, weight=1, uniform="roll_actions")
        self.save_result_button = ParticipantsPanel._button(
            self.result_actions,
            "СОХРАНИТЬ РЕЗУЛЬТАТ",
            self._save_roll_video,
            ACCENT,
            "#F1EEE5",
        )
        self.save_result_button.configure(
            font=("Segoe UI Semibold", 11),
            pady=self._px(11),
        )
        self.save_result_button.grid(
            row=0, column=0, sticky="ew", padx=(0, self._px(5))
        )
        self.cancel_result_button = ParticipantsPanel._button(
            self.result_actions,
            "ОТМЕНА",
            self._cancel_roll_result,
            SURFACE_LIGHT,
            TEXT,
        )
        self.cancel_result_button.configure(
            font=("Segoe UI Semibold", 11),
            pady=self._px(11),
        )
        self.cancel_result_button.grid(
            row=0, column=1, sticky="ew", padx=(self._px(5), 0)
        )

        self.participants_panel = ParticipantsPanel(content, self)
        self.participants_panel.grid(row=0, column=1, sticky="nsew")
        self._update_count()

    @property
    def active_participants(self) -> list[Participant]:
        return [participant for participant in self.participants if participant.enabled]

    def _clear_winner_result(self) -> None:
        self.result_var.set("")
        if self.result_card.winfo_manager():
            self.result_card.pack_forget()
        self.result_slot.configure(bg=BACKGROUND)

    def _show_winner_result(self, winner: str) -> None:
        if len(winner) <= 24:
            font_size = 18
        elif len(winner) <= 55:
            font_size = 15
        elif len(winner) <= 90:
            font_size = 12
        else:
            font_size = 10
        self.result_var.set(winner)
        self.result_caption.configure(
            text="ПОБЕДИТЕЛИ" if " | " in winner else "ПОБЕДИТЕЛЬ"
        )
        self.result_label.configure(
            font=("Segoe UI Semibold", font_size),
            wraplength=self._px(740),
        )
        self.result_slot.configure(bg=ACCENT_DARK)
        if not self.result_card.winfo_manager():
            self.result_card.pack(fill="both", expand=True, padx=1, pady=1)

    def _show_spin_controls(self) -> None:
        if self.result_actions.winfo_manager():
            self.result_actions.pack_forget()
        if not self.spin_button.winfo_manager():
            self.spin_button.pack(fill="x")

    def _show_result_controls(self) -> None:
        if self.spin_button.winfo_manager():
            self.spin_button.pack_forget()
        if not self.result_actions.winfo_manager():
            self.result_actions.pack(fill="x")

    def _set_video_ready(self, ready: bool) -> None:
        if not ready:
            self._video_preparation_failed = False
        self._refresh_result_preparation_state()

    def _refresh_result_preparation_state(self) -> None:
        if self._video_preparation_failed:
            self.button_process_text.stop()
            self.save_result_button.configure(
                state="disabled",
                text="MP4 НЕ СОЗДАН",
                bg=CTA_DISABLED,
                highlightbackground=CTA_DISABLED,
                highlightcolor=CTA_DISABLED,
            )
            return

        if self._roll_video_bytes is None or self._reward_ocr_pending:
            self.save_result_button.configure(
                state="disabled",
                bg=CTA_DISABLED,
                highlightbackground=CTA_DISABLED,
                highlightcolor=CTA_DISABLED,
            )
            process_name = (
                "ПОДГОТОВКА MP4"
                if self._roll_video_bytes is None
                else "РАСПОЗНАВАНИЕ НАГРАДЫ"
            )
            self.button_process_text.start(
                self.save_result_button,
                process_name,
            )
            return

        self.button_process_text.stop()
        self.save_result_button.configure(
            state="normal",
            text="СОХРАНИТЬ РЕЗУЛЬТАТ",
            bg=ACCENT,
            highlightbackground=ACCENT_DARK,
            highlightcolor=ACCENT_DARK,
        )

    def _begin_reward_recognition(self, winners: list[str]) -> None:
        generation = self._reward_ocr_generation
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self._pending_draw_results = [
            DrawResult(winner, "", timestamp) for winner in winners
        ]
        self._roll_logged = False

        if self._roll_prize_image is None:
            self._pending_draw_results = [
                DrawResult(winner, "Награда не указана", timestamp)
                for winner in winners
            ]
            self._reward_ocr_pending = False
            self._refresh_result_preparation_state()
            return

        prize_image = self._roll_prize_image.copy()
        self._reward_ocr_pending = True
        self._reward_ocr_jobs += 1
        self._refresh_result_preparation_state()

        def worker() -> None:
            try:
                result: str | Exception = recognize_reward_name(prize_image)
            except Exception as error:
                result = error
            self._reward_ocr_queue.put((generation, result))

        threading.Thread(target=worker, daemon=True).start()
        if not self._reward_ocr_polling:
            self._reward_ocr_polling = True
            self.after(100, self._poll_reward_recognition)

    def _poll_reward_recognition(self) -> None:
        while True:
            try:
                generation, result = self._reward_ocr_queue.get_nowait()
            except queue.Empty:
                break
            self._reward_ocr_jobs = max(0, self._reward_ocr_jobs - 1)
            if generation != self._reward_ocr_generation:
                continue
            pending = self._pending_draw_results
            if not pending:
                continue
            reward = (
                result.strip()
                if isinstance(result, str) and result.strip()
                else "Награда не распознана"
            )
            self._pending_draw_results = [
                DrawResult(item.winner, reward, item.timestamp)
                for item in pending
            ]
            self._reward_ocr_pending = False
            self._refresh_result_preparation_state()

        if self._reward_ocr_jobs:
            self.after(100, self._poll_reward_recognition)
        else:
            self._reward_ocr_polling = False

    def _commit_pending_draw_result(self) -> None:
        if self._roll_logged or not self._pending_draw_results:
            return
        try:
            self.draw_log_store.append_many(self._pending_draw_results)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(
                APP_NAME,
                f"MP4 сохранён, но не удалось записать журнал:\n{error}",
                parent=self,
            )
            return
        self._roll_logged = True
        self.participants_panel.refresh_history_dialog()

    def _draw_wheel(self) -> None:
        canvas = self.wheel_canvas
        if self._roll_slots is not None and self._roll_probabilities is not None:
            active = self._roll_slots
            probabilities = self._roll_probabilities
        else:
            active = self.active_participants
            probabilities = participant_probabilities(
                active, self.bm_influence_percent, self.participants
            )
        cx, cy, radius = self.CENTER_X, self.CENTER_Y, self.RADIUS

        self._ensure_wheel_assets(probabilities)
        image = self._wheel_background.copy()
        disc = self._wheel_disc
        if active and self.rotation % 360.0:
            if self._wheel_disc_array is None:
                self._wheel_disc_array = np.asarray(self._wheel_disc)
            disc_height, disc_width = self._wheel_disc_array.shape[:2]
            transform = cv2.getRotationMatrix2D(
                ((disc_width - 1) / 2.0, (disc_height - 1) / 2.0),
                self.rotation,
                1.0,
            )
            rotated = cv2.warpAffine(
                self._wheel_disc_array,
                transform,
                (disc_width, disc_height),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0, 0),
            )
            disc = Image.fromarray(rotated)
        image.paste(disc, self._wheel_disc_offset, disc)
        if (
            self._show_winner_glow
            and self._winner_index is not None
            and 0 <= self._winner_index < len(probabilities)
        ):
            winner_glow = self._build_winner_glow(
                probabilities, self._winner_index
            )
            image.paste(winner_glow, (0, 0), winner_glow)
        image.paste(self._wheel_overlay, (0, 0), self._wheel_overlay)
        display_image = image
        if self.display_canvas_size != self.CANVAS_SIZE:
            display_image = image.resize(
                (self.display_canvas_size, self.display_canvas_size),
                Image.Resampling.LANCZOS,
            )
        if hasattr(self, "_wheel_image"):
            self._wheel_image.paste(display_image)
        else:
            self._wheel_image = ImageTk.PhotoImage(display_image)
            canvas.create_image(0, 0, image=self._wheel_image, anchor="nw")
        canvas.delete("labels")

        if not active:
            return

        angle_offset = 0.0
        for index, participant in enumerate(active):
            segment = probabilities[index] * 360.0
            if probabilities[index] <= 0.0001:
                angle_offset += segment
                continue
            start = self.rotation + angle_offset
            middle = math.radians(start + segment / 2.0)
            label_radius = radius * (
                self.LABEL_RADIUS_RATIO
                if len(active) <= 12
                else self.DENSE_LABEL_RADIUS_RATIO
            )
            x = (cx + label_radius * math.cos(middle)) * self.ui_scale
            y = (cy - label_radius * math.sin(middle)) * self.ui_scale
            label = participant.name
            limit = 13 if len(active) <= 10 else 9
            if len(label) > limit:
                label = label[: limit - 1] + "…"
            name_size = 10 if len(active) <= 20 else 9
            probability_size = 9 if len(active) <= 12 else 8
            probability_text = f"{probabilities[index] * 100:.2f}%"
            if not self.spinning:
                canvas.create_text(
                    x + self._px(1),
                    y - self._px(6),
                    text=label,
                    fill="#090A09",
                    font=("Segoe UI Semibold", name_size),
                    width=self._px(95),
                    justify="center",
                    tags="labels",
                )
                canvas.create_text(
                    x + self._px(1),
                    y + self._px(10),
                    text=probability_text,
                    fill="#090A09",
                    font=("Segoe UI", probability_size),
                    width=self._px(95),
                    justify="center",
                    tags="labels",
                )
            canvas.create_text(
                x,
                y - self._px(7),
                text=label,
                fill=TEXT_BRIGHT,
                font=("Segoe UI Semibold", name_size),
                width=self._px(95),
                justify="center",
                tags="labels",
            )
            canvas.create_text(
                x,
                y + self._px(9),
                text=probability_text,
                fill=TEXT_BRIGHT,
                font=("Segoe UI", probability_size),
                width=self._px(95),
                justify="center",
                tags="labels",
            )
            angle_offset += segment

    def _build_winner_glow(
        self,
        probabilities: list[float],
        winner_index: int,
        rotation: float | None = None,
    ) -> Image.Image:
        """Return an antialiased gold highlight for the winning sector."""

        scale = self.DISC_ANTIALIAS_SCALE
        width = self.CANVAS_SIZE * scale
        center_x = self.CENTER_X * scale
        center_y = self.CENTER_Y * scale
        radius = self.RADIUS * scale
        segment = probabilities[winner_index] * 360.0
        rotation_value = self.rotation if rotation is None else rotation
        start = rotation_value + sum(probabilities[:winner_index]) * 360.0
        steps = max(4, math.ceil(segment / 1.5))
        points = [(center_x, center_y)]
        for step in range(steps + 1):
            angle = math.radians(start + segment * step / steps)
            points.append(
                (
                    round(center_x + radius * math.cos(angle)),
                    round(center_y - radius * math.sin(angle)),
                )
            )

        gold = ImageColor.getrgb(ACCENT)
        light_gold = ImageColor.getrgb(ACCENT_HOVER)
        winner_color = ImageColor.getrgb(WINNER_SECTOR)
        glow_seed = Image.new("RGBA", (width, width), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_seed)
        glow_draw.line(
            points + [points[0]],
            fill=(*gold, 180),
            width=5 * scale,
            joint="curve",
        )
        glow = glow_seed.filter(ImageFilter.GaussianBlur(10 * scale))

        highlight = Image.new("RGBA", (width, width), (0, 0, 0, 0))
        highlight_draw = ImageDraw.Draw(highlight)
        highlight_draw.polygon(points, fill=(*winner_color, 255))
        highlight_draw.line(
            points + [points[0]],
            fill=(*light_gold, 210),
            width=2 * scale,
            joint="curve",
        )
        glow = Image.alpha_composite(glow, highlight)

        # Let the highlight run slightly under the opaque centre emblem so
        # antialiasing cannot leave a dark seam between the sector and medallion.
        annulus = Image.new("L", (width, width), 0)
        annulus_draw = ImageDraw.Draw(annulus)
        outer_radius = radius - 5 * scale
        inner_radius = (self.CENTER_MEDALLION_RADIUS - 2) * scale
        annulus_draw.ellipse(
            (
                center_x - outer_radius,
                center_y - outer_radius,
                center_x + outer_radius,
                center_y + outer_radius,
            ),
            fill=255,
        )
        annulus_draw.ellipse(
            (
                center_x - inner_radius,
                center_y - inner_radius,
                center_x + inner_radius,
                center_y + inner_radius,
            ),
            fill=0,
        )
        glow.putalpha(ImageChops.multiply(glow.getchannel("A"), annulus))
        return glow.resize(
            (self.CANVAS_SIZE, self.CANVAS_SIZE), Image.Resampling.LANCZOS
        )

    @staticmethod
    @lru_cache(maxsize=64)
    def _recording_font(
        size: int,
        bold: bool = False,
        text: str = "",
    ) -> ImageFont.ImageFont:
        has_japanese = any("\u3040" <= char <= "\u30ff" for char in text)
        has_hangul = any("\uac00" <= char <= "\ud7af" for char in text)
        has_cjk = any("\u3400" <= char <= "\u9fff" for char in text)

        if has_japanese:
            font_names = (
                "YuGothB.ttc" if bold else "YuGothM.ttc",
                "msgothic.ttc",
                "msyhbd.ttc" if bold else "msyh.ttc",
            )
        elif has_hangul:
            font_names = (
                "malgunbd.ttf" if bold else "malgun.ttf",
                "msyhbd.ttc" if bold else "msyh.ttc",
            )
        elif has_cjk:
            font_names = (
                "msyhbd.ttc" if bold else "msyh.ttc",
                "simsunb.ttf" if bold else "simsun.ttc",
                "YuGothB.ttc" if bold else "YuGothM.ttc",
            )
        else:
            font_names = ("seguisb.ttf" if bold else "segoeui.ttf",)

        windows_root = Path(os.environ.get("WINDIR", "C:\\Windows"))
        for font_name in font_names:
            candidates = (windows_root / "Fonts" / font_name, Path(font_name))
            for candidate in candidates:
                try:
                    return ImageFont.truetype(str(candidate), size=size)
                except OSError:
                    continue

        # Preserve the old Latin/Cyrillic fallback if an optional Windows CJK
        # font is unavailable on a particular installation.
        fallback_name = "seguisb.ttf" if bold else "segoeui.ttf"
        for candidate in (
            windows_root / "Fonts" / fallback_name,
            Path(fallback_name),
        ):
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _render_recorded_wheel(
        self,
        background: Image.Image,
        disc_array: np.ndarray,
        overlay: Image.Image,
        rotation: float,
        names: list[str],
        probabilities: list[float],
        winner_index: int | None = None,
    ) -> Image.Image:
        image = background.copy()
        disc_height, disc_width = disc_array.shape[:2]
        transform = cv2.getRotationMatrix2D(
            ((disc_width - 1) / 2.0, (disc_height - 1) / 2.0),
            rotation,
            1.0,
        )
        rotated = cv2.warpAffine(
            disc_array,
            transform,
            (disc_width, disc_height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        disc = Image.fromarray(rotated)
        image.paste(disc, self._wheel_disc_offset, disc)
        if winner_index is not None:
            glow = self._build_winner_glow(
                probabilities,
                winner_index,
                rotation=rotation,
            )
            image.paste(glow, (0, 0), glow)
        image.paste(overlay, (0, 0), overlay)

        label_draw = ImageDraw.Draw(image)
        name_font_size = 14 if len(names) <= 20 else 13
        probability_font = self._recording_font(
            12 if len(names) <= 12 else 11
        )
        angle_offset = 0.0
        for index, name in enumerate(names):
            segment = probabilities[index] * 360.0
            if probabilities[index] <= 0.0001:
                angle_offset += segment
                continue
            middle = math.radians(rotation + angle_offset + segment / 2.0)
            label_radius = self.RADIUS * (
                self.LABEL_RADIUS_RATIO
                if len(names) <= 12
                else self.DENSE_LABEL_RADIUS_RATIO
            )
            x = self.CENTER_X + label_radius * math.cos(middle)
            y = self.CENTER_Y - label_radius * math.sin(middle)
            limit = 13 if len(names) <= 10 else 9
            visible_name = name if len(name) <= limit else name[: limit - 1] + "…"
            name_font = self._recording_font(
                name_font_size,
                bold=True,
                text=visible_name,
            )
            label_draw.text(
                (x, y - 7),
                visible_name,
                fill=TEXT_BRIGHT,
                font=name_font,
                anchor="mm",
                stroke_width=1,
                stroke_fill="#090A09",
            )
            label_draw.text(
                (x, y + 9),
                f"{probabilities[index] * 100:.2f}%",
                fill=TEXT_BRIGHT,
                font=probability_font,
                anchor="mm",
                stroke_width=1,
                stroke_fill="#090A09",
            )
            angle_offset += segment
        return image

    def _render_prize_snapshot(
        self, prize_image: Image.Image | None
    ) -> Image.Image:
        if prize_image is None:
            width = PrizeImageCard.EMPTY_WIDTH
            height = PrizeImageCard.EMPTY_HEIGHT
            card = Image.new("RGB", (width, height), SURFACE)
            card_draw = ImageDraw.Draw(card)
            card_draw.rectangle(
                (1, 1, width - 2, height - 2),
                outline=BORDER,
                width=2,
            )
            cx, cy = width // 2, height // 2
            card_draw.line(
                (cx - 13, cy, cx + 13, cy),
                fill=MUTED,
                width=3,
            )
            card_draw.line(
                (cx, cy - 13, cx, cy + 13),
                fill=MUTED,
                width=3,
            )
            return card

        source = prize_image.convert("RGBA")
        source.thumbnail(
            (PrizeImageCard.MAX_IMAGE_WIDTH, PrizeImageCard.MAX_IMAGE_HEIGHT),
            Image.Resampling.LANCZOS,
        )
        padding = PrizeImageCard.BORDER_PADDING
        card = Image.new(
            "RGBA",
            (source.width + padding * 2, source.height + padding * 2),
            ImageColor.getrgb(SURFACE) + (255,),
        )
        card.alpha_composite(source, (padding, padding))
        card_draw = ImageDraw.Draw(card)
        card_draw.rectangle(
            (1, 1, card.width - 2, card.height - 2),
            outline=BORDER_LIGHT,
            width=2,
        )
        return card.convert("RGB")

    def _build_video_scene_base(
        self,
        count_caption: str,
        prize_image: Image.Image | None,
        prize_quantity: int,
    ) -> Image.Image:
        scene = Image.new(
            "RGB",
            (self.LEFT_PANEL_WIDTH, self.VIDEO_CAPTURE_HEIGHT),
            BACKGROUND,
        )
        scene_draw = ImageDraw.Draw(scene)
        scene_draw.text(
            (26, 31),
            APP_NAME,
            fill=TEXT,
            font=self._recording_font(29, bold=True),
            anchor="lm",
        )
        scene_draw.text(
            (26, 72),
            count_caption,
            fill=MUTED,
            font=self._recording_font(12),
            anchor="lm",
        )
        prize = self._render_prize_snapshot(prize_image)
        prize_x = self.LEFT_PANEL_WIDTH - 22 - prize.width
        prize_y = 18 + (78 - prize.height) // 2
        scene.paste(prize, (prize_x, prize_y))
        if prize_quantity > 1:
            scene_draw.text(
                (prize_x - 12, 57),
                f"{int(prize_quantity)} X",
                fill=TEXT,
                font=self._recording_font(20, bold=True),
                anchor="rm",
            )
        return scene

    def _draw_recorded_winner_card(
        self, scene: Image.Image, winner: str
    ) -> None:
        card_box = (23, 840, self.LEFT_PANEL_WIDTH - 23, 902)
        scene_draw = ImageDraw.Draw(scene)
        scene_draw.rectangle(
            card_box,
            fill=WINNER_BACKGROUND,
            outline=ACCENT,
            width=2,
        )
        center_x = self.LEFT_PANEL_WIDTH // 2
        scene_draw.text(
            (center_x, 853),
            "ПОБЕДИТЕЛЬ",
            fill=MUTED,
            font=self._recording_font(12, bold=True),
            anchor="mm",
        )
        scene_draw.line(
            (center_x - 105, 865, center_x + 105, 865),
            fill=ACCENT,
            width=1,
        )
        if len(winner) <= 24:
            name_size = 25
        elif len(winner) <= 55:
            name_size = 20
        elif len(winner) <= 90:
            name_size = 16
        else:
            name_size = 13
        scene_draw.text(
            (center_x, 883),
            winner,
            fill=TEXT_BRIGHT,
            font=self._recording_font(name_size, bold=True, text=winner),
            anchor="mm",
        )

    def _encode_roll_video(
        self,
        recorded_frames: list[RecordedWheelFrame],
        winners_caption: str,
        prize_image: Image.Image | None,
        prize_quantity: int,
        count_caption: str,
        background: Image.Image,
        overlay: Image.Image,
        generation: int | None = None,
    ) -> bytes:
        if not recorded_frames:
            raise ValueError("Нет кадров розыгрыша для записи")
        scene_base = self._build_video_scene_base(
            count_caption,
            prize_image,
            prize_quantity,
        )
        cached_probability_key: tuple[float, ...] | None = None
        cached_disc_array: np.ndarray | None = None

        def render_scene(
            state: RecordedWheelFrame,
            final: bool = False,
        ) -> Image.Image:
            nonlocal cached_probability_key, cached_disc_array
            probability_key = tuple(
                round(value, 8) for value in state.probabilities
            )
            if (
                cached_disc_array is None
                or probability_key != cached_probability_key
            ):
                cached_disc_array = np.asarray(
                    self._build_wheel_disc(list(state.probabilities))
                )
                cached_probability_key = probability_key
            wheel = self._render_recorded_wheel(
                background,
                cached_disc_array,
                overlay,
                state.rotation,
                list(state.names),
                list(state.probabilities),
                state.winner_index,
            )
            scene = scene_base.copy()
            scene.paste(
                wheel.crop((0, 0, self.CANVAS_SIZE, self.CANVAS_HEIGHT)),
                ((self.LEFT_PANEL_WIDTH - self.CANVAS_SIZE) // 2, 96),
            )
            if final:
                self._draw_recorded_winner_card(scene, winners_caption)
            return scene

        def frames() -> Iterable[Image.Image]:
            for state in recorded_frames:
                if (
                    generation is not None
                    and generation != self._video_generation
                ):
                    raise RuntimeError("MP4 generation cancelled")
                yield render_scene(state)

            final_scene = render_scene(recorded_frames[-1], final=True)
            final_frame_count = max(
                1,
                round(self.VIDEO_FINAL_HOLD_SECONDS * self.VIDEO_FPS),
            )
            for _index in range(final_frame_count):
                if (
                    generation is not None
                    and generation != self._video_generation
                ):
                    raise RuntimeError("MP4 generation cancelled")
                yield final_scene

        return encode_mp4_frames(
            frames(),
            (self.LEFT_PANEL_WIDTH, self.VIDEO_CAPTURE_HEIGHT),
            self.VIDEO_FPS,
        )

    def _begin_video_generation(
        self,
        winners: list[str],
    ) -> None:
        recorded_frames = list(self._video_frames)
        generation = self._video_generation
        prize_image = (
            self._roll_prize_image.copy()
            if self._roll_prize_image is not None
            else None
        )
        prize_quantity = self._roll_prize_quantity
        count_caption = str(self.count_label.cget("text"))
        background = self._wheel_background.copy()
        overlay = self._wheel_overlay.copy()
        winners_caption = " | ".join(winners)
        self._video_jobs += 1

        def worker() -> None:
            try:
                result: bytes | Exception = self._encode_roll_video(
                    recorded_frames,
                    winners_caption,
                    prize_image,
                    prize_quantity,
                    count_caption,
                    background,
                    overlay,
                    generation,
                )
            except Exception as error:
                result = error
            self._video_queue.put((generation, result))

        threading.Thread(target=worker, daemon=True).start()
        if not self._video_polling:
            self._video_polling = True
            self.after(100, self._poll_video_generation)

    def _poll_video_generation(self) -> None:
        while True:
            try:
                generation, result = self._video_queue.get_nowait()
            except queue.Empty:
                break
            self._video_jobs = max(0, self._video_jobs - 1)
            if generation != self._video_generation:
                continue
            if isinstance(result, bytes):
                self._roll_video_bytes = result
                self._set_video_ready(True)
            else:
                self._roll_video_bytes = None
                self._video_preparation_failed = True
                self._refresh_result_preparation_state()
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось подготовить MP4:\n{result}",
                    parent=self,
                )

        if self._video_jobs:
            self.after(100, self._poll_video_generation)
        else:
            self._video_polling = False

    def _save_roll_video(self) -> None:
        if self._roll_video_bytes is None:
            return
        initial_name = datetime.now().strftime(
            "Розыгрыш_%Y-%m-%d_%H-%M-%S.mp4"
        )
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить результат розыгрыша",
            initialfile=initial_name,
            defaultextension=".mp4",
            filetypes=(("MP4", "*.mp4"),),
        )
        if not destination:
            return
        try:
            Path(destination).write_bytes(self._roll_video_bytes)
        except OSError as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось сохранить MP4:\n{error}",
                parent=self,
            )
            return
        self._commit_pending_draw_result()

    def _cancel_roll_result(self) -> None:
        if self.spinning:
            return
        self.button_process_text.stop()
        self._video_generation += 1
        self._reward_ocr_generation += 1
        self._roll_video_bytes = None
        self._video_frames.clear()
        self._roll_prize_image = None
        self._video_preparation_failed = False
        self._reward_ocr_pending = False
        self._pending_draw_results = []
        self._roll_logged = False
        self._winner_index = None
        self._show_winner_glow = False
        self._roll_slots = None
        self._roll_remaining = []
        self._roll_probabilities = None
        self._roll_winners = []
        self._roll_target_count = 1
        self.rotation = 0.0
        self._clear_winner_result()
        self._show_spin_controls()
        self.prize_card.set_locked(False)
        self.prize_quantity_control.set_locked(False)
        self._draw_wheel()

    def _request_wheel_redraw(self) -> None:
        active = self.active_participants
        probabilities = participant_probabilities(
            active, self.bm_influence_percent, self.participants
        )
        cache_key = tuple(round(value, 12) for value in probabilities)

        if self._wheel_cache_key == cache_key:
            self._wheel_render_generation += 1
            self._wheel_pending_key = None
            self._draw_wheel()
            return
        if self._wheel_pending_key == cache_key:
            return

        self._ensure_static_wheel_assets()
        self._wheel_render_generation += 1
        generation = self._wheel_render_generation
        self._wheel_pending_key = cache_key
        self._wheel_render_jobs += 1

        def worker() -> None:
            try:
                disc = self._build_wheel_disc(probabilities)
            except Exception:
                disc = None
            self._wheel_render_queue.put((generation, cache_key, disc))

        threading.Thread(target=worker, daemon=True).start()
        if not self._wheel_render_polling:
            self._wheel_render_polling = True
            self.after(10, self._poll_wheel_render)

    def _poll_wheel_render(self) -> None:
        newest_ready = False
        while True:
            try:
                generation, cache_key, disc = self._wheel_render_queue.get_nowait()
            except queue.Empty:
                break
            self._wheel_render_jobs = max(0, self._wheel_render_jobs - 1)
            if generation != self._wheel_render_generation:
                continue
            self._wheel_pending_key = None
            if disc is not None:
                self._wheel_disc = disc
                self._wheel_disc_array = np.asarray(disc)
                self._wheel_cache_key = cache_key
                newest_ready = True

        if newest_ready and not self.spinning:
            self._draw_wheel()

        if self._wheel_render_jobs:
            self.after(10, self._poll_wheel_render)
        else:
            self._wheel_render_polling = False

    def _ensure_wheel_assets(self, probabilities: list[float]) -> None:
        """Build only the sector layer when participant probabilities change."""
        self._ensure_static_wheel_assets()
        cache_key = tuple(round(value, 12) for value in probabilities)
        if self._wheel_cache_key == cache_key:
            return

        self._wheel_disc = self._build_wheel_disc(probabilities)
        self._wheel_disc_array = np.asarray(self._wheel_disc)
        self._wheel_cache_key = cache_key

    def _build_wheel_disc(self, probabilities: list[float]) -> Image.Image:
        """Render the mutable sector disc without accessing Tk."""

        active_count = len(probabilities) if sum(probabilities) > 1e-12 else 0

        scale = self.DISC_ANTIALIAS_SCALE
        radius = self.RADIUS

        def scaled(values: tuple[float, ...]) -> tuple[int, ...]:
            return tuple(round(value * scale) for value in values)

        disc_margin = 6
        disc_size = (radius + disc_margin) * 2
        high_disc_size = (disc_size * scale, disc_size * scale)
        disc_center = radius + disc_margin
        disc_box = (
            disc_margin,
            disc_margin,
            disc_margin + radius * 2,
            disc_margin + radius * 2,
        )
        if active_count == 0:
            disc = Image.new("RGBA", high_disc_size, (0, 0, 0, 0))
            disc_draw = ImageDraw.Draw(disc)
            disc_draw.ellipse(
                scaled(disc_box),
                fill=SURFACE,
                outline=WHEEL_METAL,
                width=3 * scale,
            )
        else:
            high_center = disc_center * scale
            wedge_radius = (radius + 4) * scale
            disc_rgb = Image.new("RGB", high_disc_size, WHEEL_COLORS[0])
            wedge_draw = ImageDraw.Draw(disc_rgb)
            angle_offset = 0.0
            for index in range(active_count):
                segment = probabilities[index] * 360.0
                start = angle_offset
                steps = max(2, math.ceil(segment / 2.0))
                points = [(high_center, high_center)]
                for step in range(steps + 1):
                    angle = math.radians(start + segment * step / steps)
                    points.append(
                        (
                            round(high_center + wedge_radius * math.cos(angle)),
                            round(high_center - wedge_radius * math.sin(angle)),
                        )
                    )
                wedge_draw.polygon(
                    points,
                    fill=WHEEL_COLORS[index % len(WHEEL_COLORS)],
                )
                angle_offset += segment

            circle_mask = Image.new("L", high_disc_size, 0)
            ImageDraw.Draw(circle_mask).ellipse(scaled(disc_box), fill=255)
            disc = disc_rgb.convert("RGBA")
            disc.putalpha(circle_mask)
            disc_draw = ImageDraw.Draw(disc)

            if active_count > 1:
                angle_offset = 0.0
                for segment_probability in probabilities:
                    angle = math.radians(angle_offset)
                    endpoint = (
                        round(high_center + radius * scale * math.cos(angle)),
                        round(high_center - radius * scale * math.sin(angle)),
                    )
                    disc_draw.line(
                        (high_center, high_center, endpoint[0], endpoint[1]),
                        fill=WHEEL_SEPARATOR,
                        width=max(2, scale),
                    )
                    angle_offset += segment_probability * 360.0
        return disc.resize((disc_size, disc_size), Image.Resampling.LANCZOS)

    def _draw_metal_rim(
        self, draw: ImageDraw.ImageDraw, scale: int
    ) -> None:
        """Draw a clean layered metal rim without a noisy texture."""

        cx = self.CENTER_X * scale
        cy = self.CENTER_Y * scale
        radius = self.RADIUS * scale

        def rim_box(inset: float) -> tuple[int, int, int, int]:
            inset_scaled = inset * scale
            return (
                round(cx - radius + inset_scaled),
                round(cy - radius + inset_scaled),
                round(cx + radius - inset_scaled),
                round(cy + radius - inset_scaled),
            )

        draw.ellipse(rim_box(0), outline=WHEEL_METAL_SHADOW, width=2 * scale)
        draw.ellipse(rim_box(2), outline=WHEEL_METAL_DARK, width=10 * scale)
        draw.ellipse(rim_box(3), outline=WHEEL_METAL, width=7 * scale)
        draw.ellipse(
            rim_box(5), outline=WHEEL_METAL_LIGHT, width=max(scale, 1)
        )
        draw.ellipse(rim_box(8), outline=WHEEL_METAL, width=2 * scale)
        draw.ellipse(rim_box(10), outline=WHEEL_METAL_DARK, width=2 * scale)

    def _draw_static_center_emblem(
        self, overlay: Image.Image, scale: int
    ) -> None:
        """Draw the centre medallion and guild icon on the fixed overlay."""

        cx = self.CENTER_X * scale
        cy = self.CENTER_Y * scale
        radius = self.CENTER_MEDALLION_RADIUS * scale
        center_box = (
            round(cx - radius),
            round(cy - radius),
            round(cx + radius),
            round(cy + radius),
        )
        center_draw = ImageDraw.Draw(overlay)
        center_draw.ellipse(center_box, fill="#181C19")

        try:
            with Image.open(resource_path("imgs", "guild icon.png")) as source:
                icon = source.convert("RGBA")
            target_size = self.GUILD_ICON_SIZE * scale
            icon = icon.resize(
                (target_size, target_size), Image.Resampling.LANCZOS
            )
            icon_x = round(cx - icon.width / 2)
            icon_y = round(cy - icon.height / 2)
            overlay.alpha_composite(icon, (icon_x, icon_y))
        except (OSError, ValueError):
            # Keep the wheel usable even if an external development asset is absent.
            pass

        center_draw = ImageDraw.Draw(overlay)
        center_draw.ellipse(
            center_box,
            outline="#777F79",
            width=2 * scale,
        )
        inner_radius = radius - 5 * scale
        center_draw.ellipse(
            (
                round(cx - inner_radius),
                round(cy - inner_radius),
                round(cx + inner_radius),
                round(cy + inner_radius),
            ),
            outline=ACCENT,
            width=max(scale, 1),
        )

    def _ensure_static_wheel_assets(self) -> None:
        if hasattr(self, "_wheel_background") and hasattr(self, "_wheel_overlay"):
            return

        scale = self.ANTIALIAS_SCALE
        size = self.CANVAS_SIZE
        cx, cy, radius = self.CENTER_X, self.CENTER_Y, self.RADIUS
        high_size = (size * scale, size * scale)

        background = Image.new("RGB", high_size, BACKGROUND)

        overlay = Image.new("RGBA", high_size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        self._draw_metal_rim(overlay_draw, scale)
        self._draw_static_center_emblem(overlay, scale)
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.polygon(
            [
                (round((cx - 17) * scale), 5 * scale),
                (round((cx + 17) * scale), 5 * scale),
                (round(cx * scale), 44 * scale),
            ],
            fill=ACCENT,
            outline=ACCENT_DARK,
            width=2 * scale,
        )
        overlay_draw.line(
            [
                (round((cx - 14) * scale), 8 * scale),
                (round(cx * scale), 40 * scale),
            ],
            fill="#C7AF70",
            width=max(2, scale),
        )

        output_size = (size, size)
        self._wheel_background = background.resize(
            output_size, Image.Resampling.LANCZOS
        )
        disc_center = radius + 6
        self._wheel_disc_offset = (cx - disc_center, cy - disc_center)
        self._wheel_overlay = overlay.resize(output_size, Image.Resampling.LANCZOS)

    def set_participants(
        self, participants: list[Participant], bm_influence_percent: float
    ) -> None:
        self.button_process_text.stop()
        participants = sort_participants_by_bm(participants)
        self.store.save(participants, bm_influence_percent)
        self.participants = participants
        self.bm_influence_percent = bm_influence_percent
        self.rotation = 0.0
        self._winner_index = None
        self._video_generation += 1
        self._reward_ocr_generation += 1
        self._roll_video_bytes = None
        self._video_frames.clear()
        self._roll_prize_image = None
        self._video_preparation_failed = False
        self._reward_ocr_pending = False
        self._pending_draw_results = []
        self._roll_logged = False
        self._show_winner_glow = False
        self._roll_slots = None
        self._roll_remaining = []
        self._roll_probabilities = None
        self._roll_winners = []
        self._roll_target_count = 1
        self._clear_winner_result()
        self._show_spin_controls()
        self.prize_card.set_locked(False)
        self.prize_quantity_control.set_locked(False)
        self._update_count()
        self._request_wheel_redraw()

    def corrected_nickname(self, recognized_name: str) -> str:
        key = nickname_lookup_key(recognized_name)
        for correction in self.nickname_corrections:
            if nickname_lookup_key(correction.recognized) == key:
                return correction.replacement
        return clean_nickname(recognized_name)

    def remember_nickname_corrections(
        self, updates: list[tuple[str, str]]
    ) -> None:
        corrections = {
            nickname_lookup_key(correction.recognized): correction
            for correction in self.nickname_corrections
        }
        for recognized_name, replacement_name in updates:
            recognized = clean_nickname(recognized_name)
            replacement = clean_nickname(replacement_name)
            key = nickname_lookup_key(recognized)
            if not key or not replacement:
                continue
            if recognized == replacement:
                corrections.pop(key, None)
            else:
                corrections[key] = NicknameCorrection(recognized, replacement)
        updated = list(corrections.values())
        self.store.save(
            self.participants,
            self.bm_influence_percent,
            updated,
        )
        self.nickname_corrections = updated

    def remove_nickname_correction(self, recognized_name: str) -> None:
        key = nickname_lookup_key(recognized_name)
        updated = [
            correction
            for correction in self.nickname_corrections
            if nickname_lookup_key(correction.recognized) != key
        ]
        if len(updated) == len(self.nickname_corrections):
            return
        self.store.save(
            self.participants,
            self.bm_influence_percent,
            updated,
        )
        self.nickname_corrections = updated

    def _update_count(self) -> None:
        active = len(self.active_participants)
        total = len(self.participants)
        if active == total:
            caption = f"Участвуют: {active}"
        else:
            caption = f"Участвуют: {active} из {total}"
        self.count_label.configure(text=caption)

    def _start_spin(self) -> None:
        if self.spinning:
            return
        self.participants_panel.flush_auto_save()
        active = self.active_participants
        if len(active) < 2:
            messagebox.showwarning(
                APP_NAME,
                "Для вращения выберите хотя бы двух участников.",
                parent=self,
            )
            return

        winner_count = self.prize_quantity_control.value()
        if winner_count > len(active):
            messagebox.showwarning(
                APP_NAME,
                "Количество наград не может превышать число выбранных "
                "участников.",
                parent=self,
            )
            return

        self.spinning = True
        self._winner_index = None
        self._show_winner_glow = False
        self._video_generation += 1
        self._reward_ocr_generation += 1
        self._roll_video_bytes = None
        self._video_preparation_failed = False
        self._reward_ocr_pending = False
        self._pending_draw_results = []
        self._roll_logged = False
        self._roll_prize_image = (
            self.prize_card.image.copy()
            if self.prize_card.image is not None
            else None
        )
        self._roll_prize_quantity = winner_count
        self._roll_target_count = winner_count
        self._roll_slots = list(active)
        self._roll_remaining = list(active)
        self._roll_winners = []
        self._roll_probabilities = self._mapped_roll_probabilities(active)
        self._video_frames = []
        self.prize_card.set_locked(True)
        self.prize_quantity_control.set_locked(True)
        self.spin_button.configure(
            state="disabled",
            bg=CTA_DISABLED,
            highlightbackground=CTA_DISABLED,
            highlightcolor=CTA_DISABLED,
        )
        self.button_process_text.start(
            self.spin_button, "КОЛЕСО ВРАЩАЕТСЯ"
        )
        self.participants_panel.set_editing_enabled(False)
        self._clear_winner_result()

        self._start_next_roll()

    def _mapped_roll_probabilities(
        self,
        pool: list[Participant],
    ) -> list[float]:
        if self._roll_slots is None:
            return []
        if not pool:
            return [0.0] * len(self._roll_slots)
        pool_probabilities = participant_probabilities(
            pool,
            self.bm_influence_percent,
            self.participants,
        )
        probability_by_identity = {
            id(participant): probability
            for participant, probability in zip(pool, pool_probabilities)
        }
        return [
            probability_by_identity.get(id(participant), 0.0)
            for participant in self._roll_slots
        ]

    def _start_next_roll(self) -> None:
        pool = list(self._roll_remaining)
        slots = self._roll_slots
        if slots is None or not pool:
            self._complete_roll()
            return

        probabilities = self._mapped_roll_probabilities(pool)
        self._roll_probabilities = probabilities
        self._winner_index = None
        self._show_winner_glow = False
        self._ensure_wheel_assets(probabilities)

        weights = participant_weights(
            pool,
            self.bm_influence_percent,
            self.participants,
        )
        pool_winner_index = weighted_random_index(weights)
        winner_participant = pool[pool_winner_index]
        winner_slot_index = next(
            index
            for index, participant in enumerate(slots)
            if participant is winner_participant
        )
        segment = probabilities[winner_slot_index] * 360.0
        winner_start = sum(probabilities[:winner_slot_index]) * 360.0
        jitter = random.uniform(-segment * 0.23, segment * 0.23)
        desired_rotation = 90.0 - (winner_start + segment / 2.0) + jitter
        delta_to_target = (desired_rotation - self.rotation) % 360.0
        multi_roll = self._roll_target_count > 1
        turns = (5 if multi_roll else 6) + secrets.randbelow(3)
        total_delta = turns * 360.0 + delta_to_target
        start_rotation = self.rotation
        duration = (
            self.MULTI_SPIN_DURATION_SECONDS
            if multi_roll
            else self.SPIN_DURATION_SECONDS
        )
        started_at = time.perf_counter()

        video_frame_count = max(1, math.ceil(duration * self.VIDEO_FPS))
        slot_names = tuple(participant.name for participant in slots)
        probability_tuple = tuple(probabilities)
        for frame_index in range(video_frame_count + 1):
            progress = frame_index / video_frame_count
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            frame_rotation = (start_rotation + total_delta * eased) % 360.0
            self._video_frames.append(
                RecordedWheelFrame(
                    frame_rotation,
                    slot_names,
                    probability_tuple,
                )
            )

        remaining = [
            participant
            for participant in pool
            if participant is not winner_participant
        ]
        end_probabilities = self._mapped_roll_probabilities(remaining)
        transition_steps = max(
            2,
            round(self.SECTOR_TRANSITION_SECONDS * self.VIDEO_FPS) + 1,
        )
        transition_probabilities: list[list[float]] = []
        for step in range(transition_steps):
            progress = step / (transition_steps - 1)
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            transition_probabilities.append(
                [
                    start + (end - start) * eased
                    for start, end in zip(probabilities, end_probabilities)
                ]
            )

        transition_discs: queue.Queue[list[Image.Image] | Exception] = (
            queue.Queue(maxsize=1)
        )

        def prepare_transition() -> None:
            try:
                discs: list[Image.Image] | Exception = [
                    self._build_wheel_disc(values)
                    for values in transition_probabilities
                ]
            except Exception as error:
                discs = error
            transition_discs.put(discs)

        if multi_roll:
            threading.Thread(target=prepare_transition, daemon=True).start()

        def animate() -> None:
            frame_started = time.perf_counter()
            elapsed = time.perf_counter() - started_at
            progress = min(1.0, elapsed / duration)
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            self.rotation = start_rotation + total_delta * eased
            self._draw_wheel()
            if progress < 1.0:
                render_ms = (time.perf_counter() - frame_started) * 1000.0
                delay_ms = max(1, round(1000.0 / 60.0 - render_ms))
                self.after(delay_ms, animate)
                return

            self.rotation %= 360.0
            self._round_stopped(
                winner_participant,
                winner_slot_index,
                probabilities,
                remaining,
                transition_probabilities,
                transition_discs,
            )

        animate()

    def _round_stopped(
        self,
        winner: Participant,
        winner_slot_index: int,
        probabilities: list[float],
        remaining: list[Participant],
        transition_probabilities: list[list[float]],
        transition_discs: queue.Queue[list[Image.Image] | Exception],
    ) -> None:
        slots = self._roll_slots
        if slots is None:
            return
        self._roll_winners.append(winner.name)
        self._winner_index = winner_slot_index
        self._show_winner_glow = True
        self._draw_wheel()

        names = tuple(participant.name for participant in slots)
        highlighted_state = RecordedWheelFrame(
            self.rotation,
            names,
            tuple(probabilities),
            winner_slot_index,
        )
        if self._roll_target_count > 1:
            hold_frames = max(
                1,
                round(self.MULTI_WINNER_HOLD_SECONDS * self.VIDEO_FPS),
            )
            self._video_frames.extend([highlighted_state] * hold_frames)
            self.after(
                round(self.MULTI_WINNER_HOLD_SECONDS * 1000),
                lambda: self._play_sector_transition(
                    remaining,
                    transition_probabilities,
                    transition_discs,
                ),
            )
            return

        self._video_frames.append(highlighted_state)
        self._complete_roll()

    def _play_sector_transition(
        self,
        remaining: list[Participant],
        transition_probabilities: list[list[float]],
        transition_discs: queue.Queue[list[Image.Image] | Exception],
    ) -> None:
        try:
            prepared = transition_discs.get_nowait()
        except queue.Empty:
            self.after(
                40,
                lambda: self._play_sector_transition(
                    remaining,
                    transition_probabilities,
                    transition_discs,
                ),
            )
            return

        if isinstance(prepared, Exception):
            prepared = [
                self._build_wheel_disc(values)
                for values in transition_probabilities
            ]

        slots = self._roll_slots
        if slots is None:
            return
        names = tuple(participant.name for participant in slots)
        self._show_winner_glow = False
        self._winner_index = None
        self._video_frames.extend(
            RecordedWheelFrame(
                self.rotation,
                names,
                tuple(values),
            )
            for values in transition_probabilities
        )
        interval_ms = max(
            1,
            round(
                self.SECTOR_TRANSITION_SECONDS
                * 1000
                / max(1, len(prepared) - 1)
            ),
        )

        def show_step(index: int) -> None:
            values = transition_probabilities[index]
            disc = prepared[index]
            self._roll_probabilities = list(values)
            self._wheel_disc = disc
            self._wheel_disc_array = np.asarray(disc)
            self._wheel_cache_key = tuple(round(value, 12) for value in values)
            self._draw_wheel()
            if index + 1 < len(prepared):
                self.after(interval_ms, lambda: show_step(index + 1))
                return

            self._roll_remaining = remaining
            if len(self._roll_winners) < self._roll_target_count:
                self.after(120, self._start_next_roll)
            else:
                self._complete_roll()

        show_step(0)

    def _complete_roll(self) -> None:
        winners = list(self._roll_winners)
        if not winners:
            return
        self.spinning = False
        self.button_process_text.stop()
        self.spin_button.configure(
            state="normal",
            text="КРУТИТЬ КОЛЕСО",
            bg=CTA_BACKGROUND,
            highlightbackground=CTA_BORDER,
            highlightcolor=CTA_BORDER,
        )
        self.participants_panel.set_editing_enabled(True)
        self.prize_card.set_locked(False)
        self.prize_quantity_control.set_locked(False)
        winners_caption = " | ".join(winners)
        self._show_winner_result(winners_caption)
        self._show_result_controls()
        self._set_video_ready(False)
        self._begin_reward_recognition(winners)
        self._begin_video_generation(winners)

    def _show_main_window(self) -> None:
        """Reveal the app only after its native frame has its final styling."""

        self._show_main_after_id = None
        self.update_idletasks()
        apply_dark_title_bar(self)
        self._maximize_window()
        apply_dark_title_bar(self)
        self.deiconify()
        self._finish_show_after_id = self.after(
            10,
            self._finish_show_main_window,
        )

    def _finish_show_main_window(self) -> None:
        self._finish_show_after_id = None
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass


def configure_windows_process() -> None:
    if os.name != "nt":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        from ctypes import windll

        windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SYNDICATE.DesktopApp"
        )
    except (AttributeError, OSError):
        pass


def main() -> None:
    configure_windows_process()
    app = WheelApp()
    app.mainloop()


if __name__ == "__main__":
    main()
