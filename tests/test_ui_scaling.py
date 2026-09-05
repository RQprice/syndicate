import unittest

from app import WheelApp


class UiScalingTests(unittest.TestCase):
    def scale_for(self, width: int, height: int) -> float:
        return WheelApp._scale_for_monitor(width, height)

    def test_full_hd_is_the_unmodified_reference_layout(self) -> None:
        self.assertEqual(self.scale_for(1920, 1080), 1.0)

    def test_smaller_and_larger_sixteen_by_nine_screens(self) -> None:
        self.assertAlmostEqual(self.scale_for(1366, 768), 768 / 1080)
        self.assertAlmostEqual(self.scale_for(2560, 1440), 4 / 3)

    def test_aspect_ratio_uses_the_limiting_dimension(self) -> None:
        self.assertEqual(self.scale_for(3440, 1440), 4 / 3)
        self.assertEqual(self.scale_for(1080, 1920), 1080 / 1920)

    def test_extreme_resolution_is_capped(self) -> None:
        self.assertEqual(self.scale_for(7680, 4320), 2.0)


if __name__ == "__main__":
    unittest.main()
