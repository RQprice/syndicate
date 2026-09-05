import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageOps

from ocr_import import recognize_reward_name


ROOT = Path(__file__).resolve().parents[1]


class RewardOcrTests(unittest.TestCase):
    @staticmethod
    def prize_expectations() -> tuple[Path, dict[str, str]]:
        samples = ROOT / "ocr_samples" / "prizes"
        rows = (samples / "expected.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        return samples, dict(row.split("\t", 1) for row in rows)

    def test_recognizes_all_manually_labeled_prize_samples(self) -> None:
        samples, expectations = self.prize_expectations()

        for filename, expected in expectations.items():
            with self.subTest(filename=filename):
                with Image.open(samples / filename) as image:
                    self.assertEqual(recognize_reward_name(image), expected)

    def test_recognizes_cards_with_different_scale_crop_and_padding(self) -> None:
        samples, expectations = self.prize_expectations()
        filenames = (
            "photo_2026-08-15_18-22-58.jpg",
            "photo_2026-08-15_17-53-18.jpg",
        )

        for filename in filenames:
            with Image.open(samples / filename) as opened:
                image = opened.convert("RGB")
            variants = {
                "small": image.resize(
                    (round(image.width * 0.7), round(image.height * 0.7)),
                    Image.Resampling.LANCZOS,
                ),
                "large": image.resize(
                    (round(image.width * 1.6), round(image.height * 1.6)),
                    Image.Resampling.LANCZOS,
                ),
                "uneven-padding": ImageOps.expand(
                    image,
                    border=(43, 17, 91, 29),
                    fill="#121513",
                ),
                "partial-icon": image.crop(
                    (round(image.height * 0.42), 0, image.width, image.height)
                ),
            }
            for variant_name, variant in variants.items():
                with self.subTest(filename=filename, variant=variant_name):
                    self.assertEqual(
                        recognize_reward_name(variant),
                        expectations[filename],
                    )

    def test_recognizes_reward_from_real_application_screenshot(self) -> None:
        screenshot = Image.open(
            ROOT / "imgs" / "Гайд" / "2 Результат розыгрыша.png"
        )
        reward_card = screenshot.crop((425, 24, 759, 92))

        self.assertEqual(
            recognize_reward_name(reward_card),
            "Книга запретных знаний мастера",
        )

    def test_joins_detected_title_and_ignores_icon_noise(self) -> None:
        output = SimpleNamespace(
            txts=("ыы", "Книга запретных", "знаний мастера", "1"),
            scores=(0.12, 0.98, 0.97, 0.99),
            boxes=(
                ((5, 20), (25, 20), (25, 40), (5, 40)),
                ((130, 30), (290, 30), (290, 55), (130, 55)),
                ((292, 30), (430, 30), (430, 55), (292, 55)),
                ((75, 60), (85, 60), (85, 75), (75, 75)),
            ),
        )
        image = Image.new("RGB", (560, 90), "#17201D")
        engine = Mock(return_value=output)

        with patch("ocr_import._get_reward_rapid_engine", return_value=engine):
            reward = recognize_reward_name(image)

        self.assertEqual(reward, "Книга запретных знаний мастера")
        engine.assert_called_once()

    def test_retries_detection_on_an_enlarged_image(self) -> None:
        missing = SimpleNamespace(txts=None, scores=None, boxes=None)
        detected = SimpleNamespace(
            txts=("Шлем Кари",),
            scores=(0.96,),
            boxes=(
                ((80, 20), (260, 20), (260, 50), (80, 50)),
            ),
        )
        image = Image.new("RGB", (252, 91), "#17201D")
        engine = Mock(side_effect=(missing, detected))

        with patch("ocr_import._get_reward_rapid_engine", return_value=engine):
            self.assertEqual(recognize_reward_name(image), "Шлем Кари")

        self.assertEqual(engine.call_count, 2)
        original_array = engine.call_args_list[0].args[0]
        enlarged_array = engine.call_args_list[1].args[0]
        self.assertEqual(enlarged_array.shape[0], original_array.shape[0] * 3)
        self.assertEqual(enlarged_array.shape[1], original_array.shape[1] * 3)


if __name__ == "__main__":
    unittest.main()
