import tkinter as tk
import unittest
from types import SimpleNamespace

from app import ScreenshotImportDialog, handle_entry_shortcut


class TextShortcutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.entry = tk.Entry(self.root)
        self.entry.pack()

    def tearDown(self) -> None:
        self.root.destroy()

    def event(self, keycode: int, keysym: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            widget=self.entry,
            keycode=keycode,
            keysym=keysym,
        )

    def test_copy_and_paste_unicode_text(self) -> None:
        self.entry.insert(0, "ネリエル")
        self.entry.selection_range(0, tk.END)

        self.assertEqual(handle_entry_shortcut(self.event(67, "с")), "break")
        self.assertEqual(self.root.clipboard_get(), "ネリエル")

        self.entry.delete(0, tk.END)
        self.assertEqual(handle_entry_shortcut(self.event(86, "м")), "break")
        self.assertEqual(self.entry.get(), "ネリエル")

    def test_paste_replaces_selected_text(self) -> None:
        self.entry.insert(0, "Старое имя")
        self.entry.selection_range(0, tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append("Новое имя")

        handle_entry_shortcut(self.event(86, "v"))

        self.assertEqual(self.entry.get(), "Новое имя")

    def test_cut_and_select_all_work_by_physical_keycode(self) -> None:
        self.entry.insert(0, "123 456")

        self.assertEqual(handle_entry_shortcut(self.event(65, "ф")), "break")
        self.assertTrue(self.entry.selection_present())
        self.assertEqual(handle_entry_shortcut(self.event(88, "ч")), "break")
        self.assertEqual(self.entry.get(), "")
        self.assertEqual(self.root.clipboard_get(), "123 456")

    def test_import_dialog_does_not_intercept_paste_in_entry(self) -> None:
        event = self.event(86, "v")

        result = ScreenshotImportDialog._on_control_keypress(object(), event)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
