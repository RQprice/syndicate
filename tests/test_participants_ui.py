import unittest
import tkinter as tk
from unittest.mock import Mock, patch

from syndicate.models import Participant
from syndicate.participants_ui import ParticipantsPanel


class ParticipantsPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = ParticipantsPanel.__new__(ParticipantsPanel)
        self.row = {"frame": object(), "name": None}
        self.panel.rows = [self.row]
        self.panel._reflow_rows = Mock()
        self.panel._refresh_select_all_state = Mock()
        self.panel._update_guild_count = Mock()
        self.panel._schedule_auto_save = Mock()

    def test_delete_row_keeps_participant_when_confirmation_is_cancelled(self) -> None:
        with patch(
            "syndicate.participants_ui.messagebox.askyesno", return_value=False
        ):
            self.panel._delete_row(self.row)

        self.assertEqual(self.panel.rows, [self.row])
        self.panel._schedule_auto_save.assert_not_called()

    def test_delete_row_removes_participant_after_confirmation(self) -> None:
        with patch(
            "syndicate.participants_ui.messagebox.askyesno", return_value=True
        ):
            self.panel._delete_row(self.row)

        self.assertEqual(self.panel.rows, [])
        self.panel._reflow_rows.assert_called_once()
        self.panel._schedule_auto_save.assert_called_once_with(0)

    def test_import_merges_duplicate_corrected_names(self) -> None:
        interpreter = tk.Tcl()
        panel = ParticipantsPanel.__new__(ParticipantsPanel)
        panel.rows = []
        panel._schedule_auto_save = Mock()

        def add_row(name: str, _enabled: bool, bm: float) -> None:
            panel.rows.append(
                {
                    "name": tk.StringVar(master=interpreter, value=name),
                    "bm": tk.StringVar(master=interpreter, value=str(bm)),
                }
            )

        panel._add_row = add_row
        panel.apply_import(
            [
                Participant("Лена", False, 100.0),
                Participant("лЕНа", False, 250.0),
            ]
        )

        self.assertEqual(len(panel.rows), 1)
        bm_var = panel.rows[0]["bm"]
        self.assertIsInstance(bm_var, tk.StringVar)
        assert isinstance(bm_var, tk.StringVar)
        self.assertEqual(bm_var.get(), "250")


if __name__ == "__main__":
    unittest.main()
