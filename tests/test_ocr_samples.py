from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image

from ocr_import import _detect_card_boxes, recognize_participants


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "ocr_samples"


class OcrSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = json.loads(
            (SAMPLES / "expected_results.json").read_text(encoding="utf-8")
        )

    def test_detects_every_card_once(self) -> None:
        for filename, expected in self.expected.items():
            with self.subTest(filename=filename), Image.open(
                SAMPLES / filename
            ) as image:
                self.assertEqual(len(_detect_card_boxes(image)), len(expected))

    def test_recognizes_exact_names_and_bm(self) -> None:
        for filename, expected in self.expected.items():
            with self.subTest(filename=filename), Image.open(
                SAMPLES / filename
            ) as image:
                actual = [
                    [participant.name, participant.bm]
                    for participant in recognize_participants(image)
                ]
                self.assertEqual(actual, expected)

    def test_recognizes_scaled_screenshots(self) -> None:
        for scale in (0.75, 1.25):
            for filename, expected in self.expected.items():
                with self.subTest(scale=scale, filename=filename), Image.open(
                    SAMPLES / filename
                ) as source:
                    image = source.convert("RGB").resize(
                        (
                            round(source.width * scale),
                            round(source.height * scale),
                        ),
                        Image.Resampling.LANCZOS,
                    )
                    actual = [
                        [participant.name, participant.bm]
                        for participant in recognize_participants(image)
                    ]
                    self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
