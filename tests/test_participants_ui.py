import unittest
import tkinter as tk
from unittest.mock import Mock, patch
from types import SimpleNamespace

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

    def test_native_popup_widget_path_does_not_schedule_broken_focus_callback(self) -> None:
        panel = self.panel
        panel._focus_move_after_id = None
        panel.owner = SimpleNamespace(nametowidget=Mock(side_effect=KeyError("native popup")))
        panel.after_idle = Mock()

        panel._clear_entry_focus_on_click(SimpleNamespace(widget=".!combobox.popdown.f.l"))

        panel.after_idle.assert_not_called()

    def test_focus_callback_handles_a_destroyed_widget_resolved_from_its_path(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            entry = tk.Entry(root)
            clicked = tk.Label(root)
            panel = self.panel
            panel._focus_move_after_id = None
            panel.owner = root
            panel._is_panel_widget = Mock(return_value=False)
            panel.after_idle = Mock(return_value="focus-job")
            with patch.object(root, "focus_get", return_value=entry):
                panel._clear_entry_focus_on_click(SimpleNamespace(widget=str(clicked)))
            callback = panel.after_idle.call_args.args[0]
            clicked.destroy()
            callback()
            self.assertIsNone(panel._focus_move_after_id)
            root.update_idletasks()
        finally:
            root.destroy()

    def test_scroll_layout_updates_are_coalesced(self) -> None:
        panel = self.panel
        panel._scroll_update_after_id = None
        panel.after_idle = Mock(return_value="scroll-job")
        for _ in range(100):
            panel._schedule_scroll_update()
        panel.after_idle.assert_called_once()

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

    def test_distribution_selection_is_independent_from_draw_selection(self) -> None:
        interpreter = tk.Tcl()
        panel = ParticipantsPanel.__new__(ParticipantsPanel)
        panel.rows = [
            {
                "enabled": tk.BooleanVar(master=interpreter, value=True),
                "distribution_enabled": {("Событие A", "Дата A"): False},
            },
            {
                "enabled": tk.BooleanVar(master=interpreter, value=False),
                "distribution_enabled": {("Событие A", "Дата A"): True},
            },
        ]
        panel._bulk_selection = False
        panel._syncing_select_all = False
        panel.select_all_var = tk.BooleanVar(master=interpreter, value=False)
        panel.select_all_check = Mock()
        panel.select_all_label = Mock()
        panel.clear_selection_button = Mock()
        panel._active_distribution_event_key = ("Событие A", "Дата A")
        panel._mass_distribution_mode = False
        panel._start_distribution_border_pulse = Mock()

        panel._switch_selection_mode(True)
        panel._mass_distribution_mode = True
        self.assertEqual(
            [row["enabled"].get() for row in panel.rows],
            [False, True],
        )

        panel.rows[0]["enabled"].set(True)
        panel.rows[1]["enabled"].set(True)
        panel._store_distribution_selection()
        panel.select_distribution_event(("Событие B", "Дата B"))
        self.assertEqual(
            [row["enabled"].get() for row in panel.rows],
            [False, False],
        )

        panel.rows[1]["enabled"].set(True)
        panel.select_distribution_event(("Событие A", "Дата A"))
        self.assertEqual(
            [row["enabled"].get() for row in panel.rows],
            [True, True],
        )

        panel._switch_selection_mode(False)
        panel._mass_distribution_mode = False

        self.assertEqual(
            [row["enabled"].get() for row in panel.rows],
            [True, False],
        )
        self.assertEqual(
            [
                row["distribution_enabled"][("Событие A", "Дата A")]
                for row in panel.rows
            ],
            [True, True],
        )

    def test_pasted_distribution_roster_changes_only_its_event(self) -> None:
        interpreter = tk.Tcl()
        event_key = ("Событие A", "Дата A")
        other_event_key = ("Событие B", "Дата B")
        owner = Mock()
        panel = ParticipantsPanel.__new__(ParticipantsPanel)
        panel.owner = owner
        panel.rows = [
            {
                "name": tk.StringVar(master=interpreter, value="Pjanka"),
                "enabled": tk.BooleanVar(master=interpreter, value=False),
                "distribution_enabled": {other_event_key: True},
            },
            {
                "name": tk.StringVar(master=interpreter, value="Пью"),
                "enabled": tk.BooleanVar(master=interpreter, value=False),
                "distribution_enabled": {other_event_key: False},
            },
            {
                "name": tk.StringVar(master=interpreter, value="Lune"),
                "enabled": tk.BooleanVar(master=interpreter, value=False),
                "distribution_enabled": {other_event_key: True},
            },
        ]
        panel._mass_distribution_mode = True
        panel._active_distribution_event_key = None

        selected = panel.apply_distribution_participants_text(
            event_key,
            "pjanka,\nПЬЮ; отсутствует",
        )

        self.assertEqual(selected, ["Pjanka", "Пью"])
        self.assertEqual(
            [row["distribution_enabled"][event_key] for row in panel.rows],
            [True, True, False],
        )
        self.assertEqual(
            [row["distribution_enabled"][other_event_key] for row in panel.rows],
            [True, False, True],
        )
        owner.update_distribution_event_participants.assert_called_once_with(
            event_key,
            ["Pjanka", "Пью"],
        )


if __name__ == "__main__":
    unittest.main()
