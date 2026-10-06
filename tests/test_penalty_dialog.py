import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from syndicate.application import WheelApp
from syndicate.models import PenaltySettings
from syndicate.storage import ParticipantStore


class PenaltySettingsDialogTests(unittest.TestCase):
    @staticmethod
    def _label_texts(widget: tk.Misc) -> set[str]:
        texts: set[str] = set()
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                texts.add(str(child.cget("text")))
            texts.update(PenaltySettingsDialogTests._label_texts(child))
        return texts

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = WheelApp()
        cls.app.withdraw()
        cls.app.update_idletasks()

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        store = ParticipantStore(
            Path(self.temporary_directory.name) / "data.json"
        )
        store.load()
        self.app.store = store
        self.app.penalty_settings = store.penalty_settings
        panel = self.app.participants_panel
        if (
            panel.penalty_dialog is not None
            and panel.penalty_dialog.winfo_exists()
        ):
            panel.penalty_dialog._close()
        panel.penalty_settings = PenaltySettings()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app.destroy()

    def test_default_scale_matches_requested_recovery_example(self) -> None:
        settings = PenaltySettings()

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.recovery_participations, 4)
        self.assertEqual(
            settings.chance_steps,
            (0.25, 0.40, 0.60, 0.80, 1.0),
        )

    def test_panel_opens_one_reusable_settings_dialog(self) -> None:
        panel = self.app.participants_panel

        panel._open_penalty_settings()
        dialog = panel.penalty_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        dialog.withdraw()

        self.assertEqual(dialog.title(), "Настройка штрафов")
        self.assertEqual(dialog.recovery_count, 4)
        self.assertEqual(
            [variable.get() for variable in dialog.stage_vars],
            ["25", "40", "60", "80", "100"],
        )
        labels = self._label_texts(dialog)
        self.assertNotIn("ШТРАФЫ ПОБЕДИТЕЛЕЙ", labels)
        self.assertNotIn(
            "Шанс восстанавливается только после участия игрока "
            "в следующем розыгрыше.",
            labels,
        )
        self.assertIn("коэффициент", labels)
        self.assertEqual(str(dialog.apply_button.cget("state")), "disabled")

        panel._open_penalty_settings()
        self.assertIs(panel.penalty_dialog, dialog)

    def test_apply_is_enabled_only_for_changed_valid_settings(self) -> None:
        panel = self.app.participants_panel
        panel._open_penalty_settings()
        dialog = panel.penalty_dialog
        assert dialog is not None
        dialog.withdraw()

        dialog.stage_vars[0].set("30")
        self.assertEqual(str(dialog.apply_button.cget("state")), "normal")

        dialog.stage_vars[0].set("25")
        self.assertEqual(str(dialog.apply_button.cget("state")), "disabled")

        dialog.stage_vars[0].set("bad value")
        self.assertEqual(str(dialog.apply_button.cget("state")), "disabled")

    def test_participation_count_has_no_fixed_max_and_list_scrolls(self) -> None:
        panel = self.app.participants_panel
        panel._open_penalty_settings()
        dialog = panel.penalty_dialog
        assert dialog is not None
        dialog.deiconify()

        for _index in range(8):
            dialog._change_count(1)
        self.app.update_idletasks()

        self.assertEqual(dialog.recovery_count, 12)
        self.assertEqual(len(dialog.stage_vars), 13)
        self.assertTrue(dialog._stages_scrollbar_visible)
        self.assertEqual(str(dialog.apply_button.cget("state")), "normal")
        dialog.withdraw()

    def test_apply_keeps_validated_ui_settings_for_reopening(self) -> None:
        panel = self.app.participants_panel
        panel._open_penalty_settings()
        dialog = panel.penalty_dialog
        assert dialog is not None
        dialog.withdraw()
        dialog.enabled_var.set(False)
        dialog._apply()

        self.assertEqual(
            panel.penalty_settings,
            PenaltySettings(
                enabled=False,
                chance_steps=(0.25, 0.40, 0.60, 0.80, 1.0),
            ),
        )
        self.assertIsNone(panel.penalty_dialog)
        reloaded = ParticipantStore(self.app.store.path)
        reloaded.load()
        self.assertEqual(reloaded.penalty_settings, panel.penalty_settings)


if __name__ == "__main__":
    unittest.main()
