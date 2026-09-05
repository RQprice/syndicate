import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image, ImageFont

from app import PrizeImageCard, PrizeQuantityControl, WheelApp


class PrizeQuantityControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.withdraw()

    def setUp(self) -> None:
        self.control = PrizeQuantityControl(self.root)

    def tearDown(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def test_buttons_and_manual_value_are_normalized(self) -> None:
        self.assertEqual(self.control.value(), 1)

        self.control.plus_button.invoke()
        self.assertEqual(self.control.value(), 2)
        self.control.minus_button.invoke()
        self.control.minus_button.invoke()
        self.assertEqual(self.control.value(), 1)

        self.control.quantity_var.set("37")
        self.assertEqual(self.control.value(), 37)
        self.control.quantity_var.set("")
        self.assertEqual(self.control.value(), 1)
        self.control.set_value(50_000)
        self.assertEqual(self.control.value(), self.control.MAXIMUM)

    def test_locked_control_keeps_its_colors_and_value(self) -> None:
        self.control.set_value(12)
        normal_background = self.control.entry.cget("bg")
        normal_foreground = self.control.entry.cget("fg")

        self.control.set_locked(True)
        self.control.plus_button.invoke()

        self.assertEqual(self.control.value(), 12)
        self.assertEqual(self.control.entry.cget("disabledbackground"), normal_background)
        self.assertEqual(self.control.entry.cget("disabledforeground"), normal_foreground)

    def test_controls_are_centered_and_removing_prize_resets_quantity(self) -> None:
        group = tk.Frame(self.root)
        group.pack()
        control = PrizeQuantityControl(group, value=8)
        control.grid(row=0, column=0)
        card = PrizeImageCard(group, on_clear=lambda: control.set_value(1))
        card.grid(row=0, column=1, padx=(4, 0))
        card.set_image(Image.new("RGB", (420, 64), "#202521"))
        self.root.update_idletasks()

        control_center = control.winfo_y() + control.winfo_height() / 2
        card_center = card.winfo_y() + card.winfo_height() / 2
        self.assertAlmostEqual(control_center, card_center, delta=1)

        card.clear()
        self.assertEqual(control.value(), 1)

    def test_single_prize_adds_no_caption_to_video_scene(self) -> None:
        recorder = SimpleNamespace(
            LEFT_PANEL_WIDTH=820,
            VIDEO_CAPTURE_HEIGHT=912,
            _recording_font=Mock(return_value=ImageFont.load_default()),
            _render_prize_snapshot=Mock(
                return_value=Image.new("RGB", (180, 56), "#202521")
            ),
        )

        WheelApp._build_video_scene_base(recorder, "Участвуют: 2", None, 1)
        self.assertEqual(recorder._recording_font.call_count, 2)

        recorder._recording_font.reset_mock()
        WheelApp._build_video_scene_base(recorder, "Участвуют: 2", None, 5)
        self.assertEqual(recorder._recording_font.call_count, 3)


if __name__ == "__main__":
    unittest.main()
