import tkinter as tk
import unittest
from unittest.mock import patch

from syndicate.theme import ACCENT, NICKNAME_BACKGROUND, NICKNAME_HOVER, ROW_HOVER
from syndicate.widgets import CopyNickname


class CopyNicknameTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.update_idletasks()
        self.root.destroy()

    def test_copies_only_nickname_and_feedback_does_not_resize_chip(self):
        nickname = "Phøenix · 玩家"
        chip = CopyNickname(self.root, nickname)
        before = (chip.cget("width"), chip.cget("height"))
        self.assertEqual(chip.itemcget(chip._feedback_text, "state"), "hidden")
        chip.copy()
        self.assertEqual(self.root.clipboard_get(), nickname)
        self.assertEqual(chip.itemcget(chip._feedback_text, "state"), "normal")
        self.assertEqual(chip.itemcget(chip._feedback_text, "text"), "Скопировано")
        self.assertEqual(chip.itemcget(chip._feedback_text, "fill"), ACCENT)
        self.assertEqual(chip._feedback_font.cget("family"), "Segoe UI Semibold")
        self.assertEqual((chip.cget("width"), chip.cget("height")), before)
        self.assertEqual(chip.coords(chip._feedback_text)[0] - chip._chip_width, 6)
        previous_job = chip._feedback_after_id
        chip.copy()
        self.assertNotEqual(chip._feedback_after_id, previous_job)
        self.assertNotIn(previous_job, self.root.tk.call("after", "info"))

    def test_feedback_fades_then_hides_and_destroy_cancels_timer(self):
        chip = CopyNickname(self.root, "NewArcher")
        chip.copy()
        chip._cancel_feedback()
        chip.configure(bg=ROW_HOVER)
        chip._fade_feedback(chip.FADE_STEPS // 2)
        self.assertNotEqual(chip.itemcget(chip._feedback_text, "fill"), ACCENT)
        self.assertEqual(chip.itemcget(chip._feedback_text, "state"), "normal")
        chip._cancel_feedback()
        chip._fade_feedback(chip.FADE_STEPS)
        self.assertEqual(chip.itemcget(chip._feedback_text, "state"), "hidden")
        self.assertIsNone(chip._feedback_after_id)
        chip.copy()
        job = chip._feedback_after_id
        chip.destroy()
        self.assertNotIn(job, self.root.tk.call("after", "info"))
        self.assertIsNone(chip._feedback_after_id)

    def test_hover_is_compact_rounded_and_long_nickname_is_copied_in_full(self):
        nickname = "ИгрокСОченьДлиннымИменем玩家" * 3
        chip = CopyNickname(self.root, nickname)
        chip.set_max_width(240)
        self.assertLessEqual(int(chip.cget("width")), 242)
        self.assertLess(chip._chip_width, int(chip.cget("width")))
        self.assertEqual(chip.type(chip._shape), "polygon")
        self.assertTrue(chip.itemcget(chip._shape, "smooth"))
        chip._set_hover(True)
        self.assertEqual(chip.itemcget(chip._shape, "fill"), NICKNAME_HOVER)
        chip.configure(bg=ROW_HOVER)
        self.assertEqual(chip.itemcget(chip._shape, "fill"), NICKNAME_HOVER)
        chip._set_hover(False)
        self.assertEqual(chip.itemcget(chip._shape, "fill"), NICKNAME_BACKGROUND)
        chip.copy()
        self.assertEqual(self.root.clipboard_get(), nickname)

    def test_clipboard_failure_does_not_show_success(self):
        chip = CopyNickname(self.root, "Asper")
        with patch.object(chip, "clipboard_append", side_effect=tk.TclError("clipboard unavailable")):
            chip.copy()
        self.assertEqual(chip.itemcget(chip._feedback_text, "state"), "hidden")
        self.assertIsNone(chip._feedback_after_id)

    def test_mouse_hover_and_click_only_apply_to_nickname_area(self):
        self.root.attributes("-alpha", 0)
        self.root.deiconify()
        chip = CopyNickname(self.root, "Phøenix")
        chip.pack()
        self.root.update()
        self.assertTrue(chip.winfo_ismapped())
        chip.event_generate("<Enter>", x=5, y=5)
        self.assertEqual(chip.itemcget(chip._shape, "fill"), NICKNAME_HOVER)
        chip.event_generate("<Button-1>", x=5, y=5)
        self.assertEqual(self.root.clipboard_get(), "Phøenix")
        self.root.clipboard_clear()
        self.root.clipboard_append("unchanged")
        chip.event_generate("<Motion>", x=chip._chip_width + 10, y=5)
        self.assertEqual(chip.itemcget(chip._shape, "fill"), NICKNAME_BACKGROUND)
        chip.event_generate("<Button-1>", x=chip._chip_width + 10, y=5)
        self.assertEqual(self.root.clipboard_get(), "unchanged")


if __name__ == "__main__":
    unittest.main()
