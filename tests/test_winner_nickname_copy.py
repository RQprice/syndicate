import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from syndicate.application import WheelApp
from syndicate.models import Participant
from syndicate.storage import DrawLogStore, MassDistributionStore, ParticipantStore
from syndicate.theme import ACCENT, MUTED, SURFACE_LIGHT, TEXT_BRIGHT, WINNER_BACKGROUND
from syndicate.widgets import CopyNickname, WinnerNicknameCopy


class WinnerNicknameCopyTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.root.geometry("460x220")
        self.card = tk.Frame(self.root, bg=WINNER_BACKGROUND)
        self.card.pack(fill="both", expand=True)
        self.caption = tk.Label(self.card, text="ПОБЕДИТЕЛЬ", bg=WINNER_BACKGROUND, fg=MUTED)
        self.caption.pack(pady=(5, 1))
        self.label = tk.Label(
            self.card, text="", bg=WINNER_BACKGROUND, fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 18), anchor="center", justify="center", wraplength=420,
        )
        self.label.pack(fill="x", pady=(1, 4))
        self.root.update()

    def tearDown(self):
        self.root.update_idletasks()
        self.root.destroy()

    def _points(self, controller):
        controller._ensure_layout()
        hits = {}
        for index in range(len(controller._lines)):
            y = controller._origin[1] + index * controller._line_height + controller._line_height // 2
            for x in range(self.label.winfo_width()):
                name = controller.nickname_at(x, y)
                if name is not None:
                    hits.setdefault(name, (x, y))
        return hits

    def test_original_label_layout_and_style_stay_unchanged(self):
        self.label.configure(text="Phøenix")
        self.root.update()
        original_geometry = [(widget.winfo_x(), widget.winfo_y(), widget.winfo_width(), widget.winfo_height())
                             for widget in (self.card, self.caption, self.label)]
        original_pack = self.label.pack_info()
        original_style = {option: self.label.cget(option) for option in ("text", "font", "bg", "fg", "wraplength")}
        controller = WinnerNicknameCopy(self.label, self.caption)
        self.root.update()
        x, y = self._points(controller)["Phøenix"]
        self.label.event_generate("<Motion>", x=x, y=y)
        self.assertEqual(self.label.cget("cursor"), "hand2")
        self.label.event_generate("<Button-1>", x=x, y=y)
        self.root.update()
        self.assertEqual(self.root.clipboard_get(), "Phøenix")
        self.assertEqual(controller._feedback_window.state(), "normal")
        self.assertEqual(controller.feedback.cget("fg"), ACCENT)
        self.assertEqual(controller.feedback.cget("bg"), SURFACE_LIGHT)
        self.assertEqual(controller.feedback.winfo_rootx(), self.label.winfo_rootx() + x)
        self.assertEqual(controller.feedback.winfo_rooty() + controller.feedback.winfo_height(),
                         self.label.winfo_rooty() + y)
        self.assertEqual(self.label.pack_info(), original_pack)
        self.assertEqual({option: self.label.cget(option) for option in original_style}, original_style)
        self.assertEqual([(widget.winfo_x(), widget.winfo_y(), widget.winfo_width(), widget.winfo_height())
                          for widget in (self.card, self.caption, self.label)], original_geometry)
        self.assertFalse(controller._mirror.winfo_manager())

    def test_overlay_stays_in_card_and_repeat_click_restarts_feedback(self):
        self.label.configure(text="Alpha | Bravo")
        self.root.update()
        controller = WinnerNicknameCopy(self.label, self.caption)
        x, y = self._points(controller)["Bravo"]
        controller._click(SimpleNamespace(x=x, y=y))
        self.root.update()
        job = controller._feedback_after_id
        self.root.clipboard_clear()
        self.root.clipboard_append("not the winner")
        controller.feedback.event_generate(
            "<Button-1>",
            x=self.label.winfo_rootx() + x + 1 - controller.feedback.winfo_rootx(),
            y=self.label.winfo_rooty() + y - 1 - controller.feedback.winfo_rooty(),
        )
        self.assertEqual(self.root.clipboard_get(), "Bravo")
        self.assertNotIn(job, self.root.tk.call("after", "info"))
        self.assertNotEqual(job, controller._feedback_after_id)

        # A wide wrapped line lets us click near both card edges.
        self.label.configure(text="W" * 100, wraplength=450)
        self.root.update()
        controller._ensure_layout()
        y = controller._origin[1] + controller._line_height // 2
        xs = [x for x in range(self.label.winfo_width()) if controller.nickname_at(x, y)]
        for x in (xs[0], xs[-1]):
            controller._copy_at(x, y)
            self.root.update()
            self.assertGreaterEqual(controller.feedback.winfo_rootx(), self.card.winfo_rootx())
            self.assertGreaterEqual(controller.feedback.winfo_rooty(), self.card.winfo_rooty())
            self.assertLessEqual(controller.feedback.winfo_rootx() + controller.feedback.winfo_width(),
                                 self.card.winfo_rootx() + self.card.winfo_width())
            self.assertLessEqual(controller.feedback.winfo_rooty() + controller.feedback.winfo_height(),
                                 self.card.winfo_rooty() + self.card.winfo_height())

    def test_each_winner_is_copied_separately_and_separators_are_not_clickable(self):
        self.label.configure(text="Alpha | Bravo | 玩家🔵")
        self.root.update()
        controller = WinnerNicknameCopy(self.label, self.caption)
        points = self._points(controller)
        self.assertEqual(set(points), {"Alpha", "Bravo", "玩家🔵"})
        for name, (x, y) in points.items():
            self.label.event_generate("<Button-1>", x=x, y=y)
            self.assertEqual(self.root.clipboard_get(), name)
        pipe_x = controller._origin[0] + controller._font.measure("Alpha ") + controller._font.measure("|") // 2
        y = controller._origin[1] + controller._line_height // 2
        self.assertIsNone(controller.nickname_at(pipe_x, y))
        self.label.event_generate("<Motion>", x=pipe_x, y=y)
        self.assertEqual(self.label.cget("cursor"), "")
        self.label.event_generate("<Button-1>", x=pipe_x, y=y)
        self.assertEqual(self.root.clipboard_get(), "玩家🔵")

    def test_wrapped_winners_and_spaces_inside_names_are_mapped_correctly(self):
        self.label.configure(text="Long Winner One | Другой Победитель | 玩家🔵", wraplength=185)
        self.root.update()
        controller = WinnerNicknameCopy(self.label, self.caption)
        points = self._points(controller)
        self.assertEqual(set(points), {"Long Winner One", "Другой Победитель", "玩家🔵"})
        self.assertGreater(len(controller._lines), 1)
        for name, (x, y) in points.items():
            controller._click(SimpleNamespace(x=x, y=y))
            self.assertEqual(self.root.clipboard_get(), name)
        for index, (_start, _end, left, _right) in enumerate(controller._lines):
            x = controller._origin[0] + int(left) - 3
            y = controller._origin[1] + index * controller._line_height + controller._line_height // 2
            self.assertIsNone(controller.nickname_at(x, y))

    def test_copy_feedback_fades_and_refresh_or_destroy_cancel_animation(self):
        self.root.attributes("-alpha", 0.01)
        self.label.configure(text="Asper")
        self.root.update()
        controller = WinnerNicknameCopy(self.label, self.caption)
        x, y = self._points(controller)["Asper"]
        controller._click(SimpleNamespace(x=x, y=y))
        job = controller._feedback_after_id
        controller.refresh()
        self.assertNotIn(job, self.root.tk.call("after", "info"))
        self.assertEqual(controller._feedback_window.state(), "withdrawn")
        controller._click(SimpleNamespace(x=x, y=y))
        controller._cancel_feedback()
        controller._fade_feedback(controller.FADE_STEPS // 2)
        self.assertAlmostEqual(float(controller._feedback_window.attributes("-alpha")), 0.005)
        self.assertEqual(controller.feedback.cget("fg"), ACCENT)
        self.assertEqual(controller.feedback.cget("bg"), SURFACE_LIGHT)
        self.assertLess(controller.FADE_STEPS * controller.FADE_INTERVAL_MS,
                        CopyNickname.FADE_STEPS * CopyNickname.FADE_INTERVAL_MS)
        controller._cancel_feedback()
        controller._fade_feedback(controller.FADE_STEPS)
        self.assertEqual(controller._feedback_window.state(), "withdrawn")
        controller._click(SimpleNamespace(x=x, y=y))
        job = controller._feedback_after_id
        self.label.destroy()
        self.assertNotIn(job, self.root.tk.call("after", "info"))
        self.assertFalse(controller._feedback_window.winfo_exists())

    def test_empty_or_changed_result_does_not_use_stale_winner(self):
        controller = WinnerNicknameCopy(self.label, self.caption)
        self.assertIsNone(controller.nickname_at(10, 10))
        self.label.configure(text="Alpha")
        self.root.update()
        self.assertEqual(set(self._points(controller)), {"Alpha"})
        self.label.configure(text="Bravo")
        self.root.update()
        self.assertEqual(set(self._points(controller)), {"Bravo"})


class WinnerNicknameCopyApplicationTests(unittest.TestCase):
    def test_sort_clear_and_ui_rebuild_keep_copying_in_sync(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            with (
                patch("syndicate.application.ParticipantStore", return_value=ParticipantStore(path / "data.json")),
                patch("syndicate.application.DrawLogStore", return_value=DrawLogStore(path / "draw_log.json")),
                patch("syndicate.application.MassDistributionStore", return_value=MassDistributionStore(path / "mass.json")),
                patch.object(WheelApp, "_draw_wheel"),
                patch.object(WheelApp, "_show_main_window"),
                patch.object(WheelApp, "_maximize_window"),
                patch.object(WheelApp, "_calculate_ui_scale", return_value=1),
            ):
                app = WheelApp()
                app.attributes("-alpha", 0)
                try:
                    app.participants = [Participant("Alpha", bm=100), Participant("Bravo", bm=200)]
                    app._roll_winners = ["Alpha", "Bravo"]
                    app._show_winner_result("Alpha | Bravo")
                    app._sort_winner_result_by_bm()
                    app.update_idletasks()
                    app.winner_nickname_copy._ensure_layout()
                    self.assertEqual([name for _start, _end, name in app.winner_nickname_copy._ranges], ["Bravo", "Alpha"])
                    old_label = app.result_label
                    app._rebuild_scaled_ui(0.8)
                    app.update_idletasks()
                    self.assertFalse(old_label.winfo_exists())
                    self.assertEqual(app.result_var.get(), "Bravo | Alpha")
                    self.assertIs(app.winner_nickname_copy.label, app.result_label)
                    app._clear_winner_result()
                    self.assertEqual(app.winner_nickname_copy._feedback_window.state(), "withdrawn")
                    self.assertIsNone(app.winner_nickname_copy.nickname_at(0, 0))
                finally:
                    app.destroy()


if __name__ == "__main__":
    unittest.main()
