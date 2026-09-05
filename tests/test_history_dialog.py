import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import DrawLogStore, DrawResult, WheelApp, handle_entry_shortcut


class DrawHistoryDialogTests(unittest.TestCase):
    @staticmethod
    def _visible_field_texts(dialog: tk.Toplevel) -> set[str]:
        return {
            widget.get()
            for row in dialog.rows_frame.winfo_children()
            for content in row.winfo_children()
            for widget in content.winfo_children()
            if isinstance(widget, tk.Entry)
        }

    def test_dialog_displays_and_deletes_selected_result(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = WheelApp()
            app.withdraw()
            try:
                store = DrawLogStore(Path(folder) / "draw_log.json")
                first = DrawResult(
                    "Sciel",
                    "Книга запретных знаний мастера",
                    "2026-01-01T20:00:00+03:00",
                )
                second = DrawResult(
                    "ネリエル",
                    "Шлем Кари",
                    "2026-01-02T21:15:00+03:00",
                )
                store.append(first)
                store.append(second)
                app.draw_log_store = store

                app.participants_panel._open_history()
                dialog = app.participants_panel.history_dialog
                self.assertIsNotNone(dialog)
                assert dialog is not None
                dialog.withdraw()
                app.update_idletasks()

                self.assertEqual(dialog.count_label.cget("text"), "· 2")
                fields = [
                    widget
                    for row in dialog.rows_frame.winfo_children()
                    for content in row.winfo_children()
                    for widget in content.winfo_children()
                    if isinstance(widget, tk.Entry)
                ]
                texts = {field.get() for field in fields}
                self.assertIn("ネリエル", texts)
                self.assertIn("Шлем Кари", texts)
                self.assertIn("02.01.2026 21:15", texts)
                self.assertTrue(
                    all(str(field.cget("state")) == "readonly" for field in fields)
                )

                reward_field = next(
                    field for field in fields if field.get() == "Шлем Кари"
                )
                reward_field.selection_range(0, tk.END)
                handle_entry_shortcut(
                    SimpleNamespace(
                        widget=reward_field,
                        keycode=67,
                        keysym="c",
                    )
                )
                self.assertEqual(app.clipboard_get(), "Шлем Кари")

                with patch("app.messagebox.askyesno", return_value=True):
                    dialog._delete(1)

                self.assertEqual(store.load(), [first])
                self.assertEqual(dialog.count_label.cget("text"), "· 1")
            finally:
                app.destroy()

    def test_delete_confirmation_can_cancel_history_removal(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = WheelApp()
            app.withdraw()
            try:
                store = DrawLogStore(Path(folder) / "draw_log.json")
                result = DrawResult(
                    "Pjanka",
                    "Шлем Кари",
                    "2026-01-01T20:00:00+03:00",
                )
                store.append(result)
                app.draw_log_store = store

                app.participants_panel._open_history()
                dialog = app.participants_panel.history_dialog
                self.assertIsNotNone(dialog)
                assert dialog is not None
                dialog.withdraw()
                app.after(80, app.quit)
                app.mainloop()
                dialog.withdraw()

                with patch("app.messagebox.askyesno", return_value=False):
                    dialog._delete(0)

                self.assertEqual(store.load(), [result])
                self.assertEqual(dialog.count_label.cget("text"), "· 1")
            finally:
                app.destroy()

    def test_search_filters_by_winner_and_reward_dynamically(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            app = WheelApp()
            app.withdraw()
            try:
                store = DrawLogStore(Path(folder) / "draw_log.json")
                first = DrawResult(
                    "Pjanka",
                    "Шлем Кари",
                    "2026-01-01T20:00:00+03:00",
                )
                second = DrawResult(
                    "ネリエル",
                    "Книга мастера",
                    "2026-01-02T21:15:00+03:00",
                )
                store.append(first)
                store.append(second)
                app.draw_log_store = store

                app.participants_panel._open_history()
                dialog = app.participants_panel.history_dialog
                self.assertIsNotNone(dialog)
                assert dialog is not None
                dialog.withdraw()

                dialog.search_var.set("pJa")
                app.update_idletasks()
                self.assertEqual(dialog.count_label.cget("text"), "· 1 из 2")
                self.assertEqual(
                    self._visible_field_texts(dialog),
                    {"Pjanka", "Шлем Кари", "01.01.2026 20:00"},
                )

                dialog.search_var.set("МАСТЕРА")
                app.update_idletasks()
                self.assertEqual(dialog.count_label.cget("text"), "· 1 из 2")
                self.assertEqual(
                    self._visible_field_texts(dialog),
                    {"ネリエル", "Книга мастера", "02.01.2026 21:15"},
                )

                dialog.search_var.set("нет совпадений")
                app.update_idletasks()
                self.assertEqual(dialog.count_label.cget("text"), "· 0 из 2")
                self.assertEqual(self._visible_field_texts(dialog), set())

                dialog.search_var.set("")
                dialog.set_date_filter(date(2026, 1, 2), date(2026, 1, 2))
                app.update_idletasks()
                self.assertEqual(dialog.count_label.cget("text"), "· 1 из 2")
                self.assertEqual(
                    self._visible_field_texts(dialog),
                    {"ネリエル", "Книга мастера", "02.01.2026 21:15"},
                )

                dialog.search_var.set("Pjanka")
                app.update_idletasks()
                self.assertEqual(dialog.count_label.cget("text"), "· 0 из 2")
                self.assertEqual(self._visible_field_texts(dialog), set())

                dialog.search_var.set("")
                dialog.set_date_filter(None, None)
                app.update_idletasks()
                self.assertEqual(dialog.count_label.cget("text"), "· 2")
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
