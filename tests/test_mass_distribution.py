import tkinter as tk
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from syndicate.mass_distribution_ui import (
    DistributionParseError,
    MassDistributionPanel,
    parse_distribution_events,
)
from syndicate.theme import ACCENT, BORDER, DANGER
from syndicate.storage import MassDistributionStore


SAMPLE = "\n".join(
    (
        "Кровь Имира\t100\tПоле боя вызова\t08-10-2026 13:20:48 (UTC-4)",
        "Верх Кари\t1\tПоле боя вызова\t08-10-2026 13:20:48 (UTC-4)",
        "Перчатки Кари\t1\tПоле боя вызова\t08-10-2026 13:10:29 (UTC-4)",
        "Пакет фрагментов gWEMIX\t6\tБлестящий остров сада\t03-10-2026 20:11:56 (UTC-4)",
    )
)


class DistributionParserTests(unittest.TestCase):
    def test_raffle_items_cannot_be_enabled_until_removed_from_their_tab(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            saved_lists = []
            panel = MassDistributionPanel(
                root, ui_scale=1, divisible_items=["Кровь Имира"],
                on_raffle_items_changed=lambda names: saved_lists.append(list(names)),
            )
            events = parse_distribution_events(SAMPLE)
            panel.set_events(events)
            armor = panel.event_cards[0]["items"][1]
            self.assertIsNone(armor["split_button"])
            armor["raffle_button"].invoke()
            self.assertEqual(panel.raffle_items, ["Верх Кари"])
            self.assertFalse(armor["enabled_var"].get())
            self.assertNotIn("Верх Кари", [item.name for _event, item in panel.selected_items()])
            self.assertEqual(str(armor["checkbox"].cget("state")), "disabled")
            armor["checkbox"]._toggle()
            self.assertFalse(armor["enabled_var"].get())
            armor["enabled_var"].set(True)
            self.assertFalse(armor["enabled_var"].get())
            self.assertNotIn("Верх Кари", [item.name for _event, item in panel.selected_items()])
            panel.set_events(events)
            self.assertFalse(panel.event_cards[0]["items"][1]["enabled_var"].get())

            panel._open_item_settings()
            dialog = panel._item_settings_dialog
            self.assertEqual(set(dialog.tab_buttons), {"divisible", "raffle"})
            dialog.select_tab("raffle")
            self.assertEqual(dialog.names, ["Верх Кари"])
            dialog.rows[0]["delete"]._activate()
            self.assertEqual(saved_lists[-1], [])
            self.assertEqual(panel.raffle_items, [])
            armor = panel.event_cards[0]["items"][1]
            self.assertEqual(str(armor["checkbox"].cget("state")), "normal")
            armor["checkbox"]._toggle()
            self.assertTrue(armor["enabled_var"].get())
            self.assertEqual(panel.divisible_items, ["Кровь Имира"])
            dialog.select_tab("divisible")
            self.assertEqual(dialog.names, ["Кровь Имира"])
            panel.set_events(events)
            self.assertTrue(panel.event_cards[0]["items"][1]["enabled_var"].get())
            dialog.destroy()
            root.update_idletasks()
        finally:
            root.destroy()

    def test_enabling_event_selects_all_rewards_except_raffle_items(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            panel = MassDistributionPanel(root, ui_scale=1, raffle_items=["Верх Кари", "Перчатки Кари"])
            panel.set_events(parse_distribution_events(
                SAMPLE + "\nОжерелье\t1\tПоле боя вызова\t08-10-2026 13:20:48 (UTC-4)"
            ))
            first = panel.event_cards[0]
            first["enabled_var"].set(False)
            self.assertTrue(all(not row["enabled_var"].get() for row in first["items"]))
            first["enabled_var"].set(True)
            self.assertEqual([row["enabled_var"].get() for row in first["items"]], [True, False, True])
            first["items"][0]["enabled_var"].set(False)
            self.assertTrue(first["enabled_var"].get())
            first["items"][2]["enabled_var"].set(False)
            self.assertFalse(first["enabled_var"].get())
            first["items"][0]["enabled_var"].set(True)
            self.assertTrue(first["enabled_var"].get())
            self.assertFalse(first["items"][2]["enabled_var"].get())

            second = panel.event_cards[1]
            self.assertFalse(second["enabled_var"].get())
            second["enabled_var"].set(True)
            self.assertFalse(second["enabled_var"].get())
            self.assertFalse(second["items"][0]["enabled_var"].get())
            root.update_idletasks()
        finally:
            root.destroy()

    def test_groups_items_by_event_and_exact_timestamp(self) -> None:
        events = parse_distribution_events(SAMPLE)

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].name, "Поле боя вызова")
        self.assertEqual(events[0].timestamp, "08-10-2026 13:20:48 (UTC-4)")
        self.assertEqual(
            [(item.name, item.quantity) for item in events[0].items],
            [("Кровь Имира", 100), ("Верх Кари", 1)],
        )

    def test_invalid_rows_report_their_line_number(self) -> None:
        with self.assertRaisesRegex(DistributionParseError, "Строка 2"):
            parse_distribution_events(
                "Предмет\t1\tСобытие\tДата\nстрока без табуляции"
            )

    def test_event_and_item_checkboxes_filter_selected_items(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            selected_events: list[tuple[str, str] | None] = []
            panel = MassDistributionPanel(
                root,
                ui_scale=1.0,
                on_event_selected=selected_events.append,
            )
            self.assertEqual(str(panel.clear_button.cget("state")), "disabled")
            panel.set_events(parse_distribution_events(SAMPLE))
            self.assertEqual(str(panel.clear_button.cget("state")), "normal")

            first_card = panel.event_cards[0]
            self.assertEqual(first_card["chevron"].grid_info()["row"], 2)
            self.assertEqual(first_card["chevron"].grid_info()["sticky"], "sw")
            self.assertEqual(first_card["checkbox"].grid_info()["rowspan"], 2)
            self.assertEqual(
                first_card["participant_clipboard_icon"].grid_info()["row"], 2
            )
            panel._toggle_event(first_card)
            self.assertEqual(
                selected_events[-1],
                ("Поле боя вызова", "08-10-2026 13:20:48 (UTC-4)"),
            )
            self.assertEqual(first_card["frame"].cget("highlightbackground"), ACCENT)
            self.assertEqual(
                first_card["participants_label"].cget("text"),
                "необходимо выбрать участников",
            )
            self.assertEqual(first_card["participants_label"].cget("fg"), DANGER)
            panel.set_event_participants(
                first_card["event"].key,
                ["Pjanka", "Пью"],
            )
            self.assertEqual(
                first_card["participants_label"].cget("text"),
                "Pjanka, Пью",
            )
            panel._use_participant_clipboard(first_card)
            self.assertEqual(root.clipboard_get(), "Pjanka, Пью")
            first_items = first_card["items"]
            assert isinstance(first_items, list)
            first_item = first_items[0]
            first_item["enabled_var"].set(False)
            self.assertNotIn(
                "Кровь Имира",
                [item.name for _event, item in panel.selected_items()],
            )

            first_card["enabled_var"].set(False)
            self.assertNotIn(
                "Верх Кари",
                [item.name for _event, item in panel.selected_items()],
            )
            self.assertTrue(
                all(not item["enabled_var"].get() for item in first_items)
            )
            first_item["enabled_var"].set(True)
            self.assertTrue(first_card["enabled_var"].get())
            first_item["enabled_var"].set(False)
            self.assertFalse(first_card["enabled_var"].get())

            second_card = panel.event_cards[1]
            panel._toggle_event(second_card)
            self.assertFalse(first_card["expanded"])
            self.assertFalse(first_card["body"].winfo_manager())
            self.assertEqual(first_card["frame"].cget("highlightbackground"), BORDER)
            self.assertTrue(second_card["expanded"])
            self.assertEqual(second_card["frame"].cget("highlightbackground"), ACCENT)
            panel.clear()
            self.assertEqual(str(panel.clear_button.cget("state")), "disabled")
            root.update_idletasks()
        finally:
            root.destroy()

    def test_distribution_ui_saves_checked_rewards_clears_draft_and_blocks_duplicate_import(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as folder:
                store = MassDistributionStore(Path(folder) / "mass_distribution_log.json")
                panel = MassDistributionPanel(
                    root, ui_scale=1.0,
                    on_distribute=lambda requests: store.distribute(requests, []),
                    on_load_reports=lambda: store.load()["reports"],
                )
                panel.set_events(parse_distribution_events(SAMPLE))
                first = panel.event_cards[0]
                panel.set_event_participants(first["event"].key, ["А", "Б"])
                first["items"][0]["enabled_var"].set(False)
                for card in panel.event_cards[1:]:
                    card["enabled_var"].set(False)
                with patch("syndicate.mass_distribution_ui.DistributionReportDialog") as dialog:
                    panel._distribute()
                report = store.load()["reports"][0]
                self.assertEqual(len(report["events"]), 1)
                self.assertEqual([item["name"] for item in report["events"][0]["items"]], ["Верх Кари"])
                dialog.assert_called_once()
                self.assertEqual(dialog.call_args.kwargs["initial_report"], report)
                self.assertFalse(panel.events)
                self.assertFalse(panel.event_cards)
                self.assertFalse(first["frame"].winfo_exists())
                self.assertIsNone(panel._active_event_key)
                self.assertFalse(panel.snapshot())
                self.assertEqual(str(panel.clear_button.cget("state")), "disabled")
                self.assertEqual(str(panel.distribute_button.cget("state")), "disabled")

                # Reopening the same export still recognises its saved occurrence.
                panel.set_events(parse_distribution_events(SAMPLE))
                first = panel.event_cards[0]
                self.assertEqual(str(first["checkbox"].cget("state")), "disabled")
                self.assertEqual(first["participant_names"], ["А", "Б"])
                self.assertIn("распределено", first["title_label"].cget("text"))
                self.assertEqual(len(panel._distribution_requests()), 2)
                root.update_idletasks()
        finally:
            root.destroy()

    def test_failed_distribution_keeps_events_rewards_and_participants(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            for error in (OSError("Не удалось сохранить"), ValueError("Нет участников")):
                with self.subTest(error=type(error).__name__):
                    selected_events = []

                    def fail_distribution(_requests, failure=error):
                        raise failure

                    panel = MassDistributionPanel(
                        root, ui_scale=1, on_event_selected=selected_events.append,
                        on_distribute=fail_distribution,
                    )
                    panel.set_events(parse_distribution_events(SAMPLE))
                    first = panel.event_cards[0]
                    panel.set_event_participants(first["event"].key, ["А", "Б"])
                    panel._toggle_event(first)
                    first["items"][0]["enabled_var"].set(False)
                    before = panel.snapshot()
                    with (
                        patch("syndicate.mass_distribution_ui.messagebox.showerror") as show_error,
                        patch("syndicate.mass_distribution_ui.DistributionReportDialog") as dialog,
                    ):
                        panel._distribute()
                    show_error.assert_called_once()
                    dialog.assert_not_called()
                    self.assertEqual(panel.snapshot(), before)
                    self.assertTrue(first["frame"].winfo_exists())
                    self.assertEqual(panel._active_event_key, first["event"].key)
                    self.assertEqual(selected_events[-1], first["event"].key)
                    self.assertEqual(str(panel.clear_button.cget("state")), "normal")
                    panel.destroy()
            root.update_idletasks()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
