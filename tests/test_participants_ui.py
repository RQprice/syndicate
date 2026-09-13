import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from syndicate.participants_ui import ParticipantsPanel


class ParticipantsPanelDeletionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
