import unittest
from pathlib import Path

from app import WheelApp


class RecordingFontTests(unittest.TestCase):
    def test_japanese_name_uses_a_japanese_font(self) -> None:
        font = WheelApp._recording_font(18, True, "ネリエル")

        self.assertIn(
            Path(getattr(font, "path", "")).name.lower(),
            {"yugothb.ttc", "msgothic.ttc", "msyhbd.ttc"},
        )
        self.assertGreater(len({bytes(font.getmask(char)) for char in "ネリエル"}), 1)

    def test_chinese_name_uses_a_cjk_font(self) -> None:
        font = WheelApp._recording_font(18, True, "走召食反木甬")

        self.assertIn(
            Path(getattr(font, "path", "")).name.lower(),
            {"msyhbd.ttc", "simsunb.ttf", "yugothb.ttc"},
        )

    def test_latin_and_cyrillic_keep_segoe_ui(self) -> None:
        latin = WheelApp._recording_font(18, True, "JokerYurbas")
        cyrillic = WheelApp._recording_font(18, True, "лена")

        self.assertEqual(Path(getattr(latin, "path", "")).name.lower(), "seguisb.ttf")
        self.assertEqual(Path(getattr(cyrillic, "path", "")).name.lower(), "seguisb.ttf")

    def test_font_instances_are_cached_between_video_frames(self) -> None:
        first = WheelApp._recording_font(18, True, "ネリエル")
        second = WheelApp._recording_font(18, True, "ネリエル")

        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
