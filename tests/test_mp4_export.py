import tempfile
import unittest
from pathlib import Path

import cv2
from PIL import Image, ImageDraw

from syndicate.video import encode_mp4_frames


class Mp4ExportTests(unittest.TestCase):
    def test_encoded_mp4_is_compact_and_readable(self) -> None:
        frames = []
        for index in range(18):
            frame = Image.new("RGB", (320, 240), "#121513")
            draw = ImageDraw.Draw(frame)
            draw.rectangle((20 + index * 4, 80, 100 + index * 4, 160), fill="#A78C4D")
            draw.text((112, 112), f"Frame {index}", fill="#D5D9D5")
            frames.append(frame)

        payload = encode_mp4_frames(frames, (320, 240), 18)

        self.assertIn(b"ftyp", payload[:64])
        self.assertLess(len(payload), 1_000_000)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.mp4"
            path.write_bytes(payload)
            capture = cv2.VideoCapture(str(path))
            try:
                self.assertTrue(capture.isOpened())
                self.assertEqual(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), 320)
                self.assertEqual(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), 240)
                self.assertGreaterEqual(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 18)
                readable, frame = capture.read()
                self.assertTrue(readable)
                self.assertIsNotNone(frame)
            finally:
                capture.release()

    def test_mp4_requires_even_dimensions(self) -> None:
        with self.assertRaises(ValueError):
            encode_mp4_frames([], (319, 240), 18)


if __name__ == "__main__":
    unittest.main()
