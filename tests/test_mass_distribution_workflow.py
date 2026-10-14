from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
import tkinter as tk
from unittest.mock import patch

from syndicate.application import WheelApp
from syndicate.mass_distribution_dialogs import DistributionReportDialog, ItemSettingsDialog
from syndicate.mass_distribution_ui import MassDistributionPanel, parse_distribution_events
from syndicate.models import Participant
from syndicate.storage import DrawLogStore, MassDistributionStore, ParticipantStore
from syndicate.theme import ACCENT, BORDER, NICKNAME_HOVER, ROW_HOVER, SURFACE


class MassDistributionWorkflowTests(unittest.TestCase):
    def test_wheel_scrolls_event_and_report_backgrounds_and_gaps(self):
        root = tk.Tk()
        root.attributes("-alpha", 0)
        root.geometry("700x400")
        try:
            panel = MassDistributionPanel(root, ui_scale=1)
            panel.pack(fill="both", expand=True)
            panel.set_events(parse_distribution_events("\n".join(
                f"Предмет\t1\tСобытие {index}\t12-10-2026 13:00:00 (UTC-4)"
                for index in range(20)
            )))
            root.update_idletasks()
            self.assertTrue(panel._scrollbar_visible)
            with patch.object(panel.canvas, "yview_scroll") as scroll:
                for surface in (panel.events_frame, panel.canvas, panel.canvas.master, panel.canvas.master.master):
                    surface.event_generate("<MouseWheel>", delta=-120)
                    scroll.assert_called_once_with(3, "units")
                    scroll.reset_mock()
            report = {
                "id": "scroll", "created_at": "2026-10-12T12:00:00+03:00",
                "events": [{
                    "name": event.name, "timestamp": event.timestamp,
                    "participants": ["А"],
                    "items": [{"name": "Предмет", "quantity": 1, "divisible": False,
                               "allocations": [{"participant": "А", "quantity": 1}]}],
                } for event in panel.events],
            }
            dialog = DistributionReportDialog(root, [report] * 20, ui_scale=1)
            dialog.deiconify()
            dialog.geometry("700x400")
            root.update_idletasks()
            self.assertTrue(dialog._scrollbar_visible)
            self.assertLessEqual(abs(
                dialog.report_cards[0]["frame"].winfo_width() - dialog.report_cards[1]["frame"].winfo_width()
            ), 1)
            with patch.object(dialog.canvas, "yview_scroll") as scroll:
                for surface in (dialog.rows_frame, dialog.canvas, dialog.canvas.master,
                                dialog.report_cards[0]["frame"], dialog.report_cards[0]["frame"].master):
                    surface.event_generate("<MouseWheel>", delta=-120)
                    scroll.assert_called_once_with(3, "units")
                    scroll.reset_mock()
            dialog.report_cards[0]["title"].event_generate("<Button-1>")
            root.update_idletasks()
            self.assertIs(dialog.current_report, report)
            self.assertTrue(dialog._scrollbar_visible)
            with patch.object(dialog.canvas, "yview_scroll") as scroll:
                for surface in (dialog.rows_frame, dialog.canvas, dialog.canvas.master, dialog.event_cards[0]["frame"]):
                    surface.event_generate("<MouseWheel>", delta=-120)
                    scroll.assert_called_once_with(3, "units")
                    scroll.reset_mock()
            dialog._toggle_event_card(dialog.event_cards[0])
            root.update_idletasks()
            row = dialog.item_rows[0]
            nickname_chip = row["recipient_buttons"][0]
            dialog._enter_report_row(row)
            self.assertEqual(row["frame"].cget("bg"), ROW_HOVER)
            nickname_chip.event_generate("<Enter>", x=5, y=5)
            self.assertTrue(nickname_chip._hovered)
            self.assertIsNone(dialog._hovered_row)
            self.assertEqual(row["frame"].cget("bg"), SURFACE)
            self.assertEqual(nickname_chip.itemcget(nickname_chip._shape, "fill"), NICKNAME_HOVER)
            nickname_chip.event_generate("<Motion>", x=nickname_chip._chip_width + 5, y=5)
            self.assertIs(dialog._hovered_row, row)
            self.assertEqual(row["frame"].cget("bg"), ROW_HOVER)
            nickname_chip.event_generate("<Motion>", x=5, y=5)
            self.assertIsNone(dialog._hovered_row)
            self.assertEqual(row["frame"].cget("bg"), SURFACE)
            nickname_chip.copy()
            self.assertEqual(nickname_chip.itemcget(nickname_chip._feedback_text, "fill"), ACCENT)
            self.assertEqual(nickname_chip.FADE_STEPS, 18)
            self.assertEqual(nickname_chip.FADE_INTERVAL_MS, 65)
            dialog.destroy()
        finally:
            root.destroy()

    def test_report_event_order_and_bottom_padding_survive_navigation(self):
        root = tk.Tk()
        root.withdraw()
        try:
            report = {
                "id": "order", "created_at": "2026-10-12T12:00:00+03:00",
                "events": [{
                    "name": name, "timestamp": "12-10-2026 13:00:00 (UTC-4)",
                    "source_position": position, "participants": [recipient],
                    "items": [{"name": "Предмет", "quantity": 1, "divisible": False,
                               "allocations": [{"participant": recipient, "quantity": 1}]}],
                } for name, position, recipient in (("Второе", 1, "А"), ("Первое", 0, "А"), ("Третье", 2, "Б"))],
            }
            dialog = DistributionReportDialog(root, [report], ui_scale=1)
            self.assertFalse(dialog.event_cards)
            self.assertIsNone(dialog.current_report)
            self.assertEqual(dialog.report_cards[0]["title"].cget("text"), "Распределение 12.10")
            self.assertEqual(dialog.report_cards[0]["summary"].cget("text"), "Участников: 2 · Предметов: 3 · Событий: 3")
            self.assertEqual(dialog.report_cards[0]["frame"].master.pack_info()["pady"], 7)
            self.assertFalse(dialog.header.winfo_manager())
            self.assertFalse(hasattr(dialog, "heading_label"))
            self.assertFalse(hasattr(dialog, "selector"))
            self.assertFalse(hasattr(dialog, "search_var"))
            self.assertFalse(hasattr(dialog, "copy_button"))
            dialog._show_report(dialog.report_cards[0]["report"])
            self.assertEqual([card["event"]["name"] for card in dialog.event_cards], ["Первое", "Второе", "Третье"])
            self.assertEqual(dialog.event_cards[0]["frame"].pack_info()["pady"], (7, 0))
            self.assertEqual(dialog.event_cards[-1]["frame"].pack_info()["pady"], 7)
            self.assertFalse(dialog.item_rows)
            self.assertTrue(all(not card["expanded"] for card in dialog.event_cards))
            dialog._toggle_event_card(dialog.event_cards[0])
            self.assertEqual(dialog.event_cards[0]["frame"].cget("highlightbackground"), ACCENT)
            self.assertEqual(dialog.event_cards[0]["frame"].cget("highlightcolor"), ACCENT)
            original_row = dialog.item_rows[0]["name_label"]
            dialog.back_button.invoke()
            self.assertFalse(original_row.winfo_exists())
            self.assertFalse(dialog.event_cards)
            self.assertIsNone(dialog.current_report)
            dialog._show_report(dialog.report_cards[0]["report"])
            self.assertEqual([card["event"]["name"] for card in dialog.event_cards], ["Первое", "Второе", "Третье"])
            self.assertEqual(dialog.event_cards[2]["frame"].pack_info()["pady"], 7)
            self.assertFalse(dialog.item_rows)
            self.assertTrue(all(not card["expanded"] for card in dialog.event_cards))
            dialog.destroy()
            root.update_idletasks()
        finally:
            root.destroy()

    def test_report_loads_only_open_event_and_preserves_item_order(self):
        root = tk.Tk()
        root.withdraw()
        try:
            report = {
                "id": "test", "created_at": "2026-10-12T12:00:00+03:00",
                "events": [{
                    "name": "Поле боя", "timestamp": "12-10-2026 13:00:00 (UTC-4)",
                    "participants": ["А", "Б"],
                    "items": [
                        {"name": name, "quantity": 1, "divisible": False,
                         "source_position": position,
                         "allocations": [{"participant": recipient, "quantity": 1}]}
                        for name, position, recipient in (("Амулет", 1, "Б"), ("Меч", 2, "А"), ("Щит", 0, "А"))
                    ],
                }],
            }
            second_event = deepcopy(report["events"][0])
            second_event["name"] = "Другое событие"
            report["events"].append(second_event)
            dialog = DistributionReportDialog(root, [report], ui_scale=1, initial_report=report)
            self.assertIs(dialog.current_report, report)
            self.assertFalse(dialog.report_cards)
            self.assertFalse(dialog.item_rows)
            self.assertTrue(all(card["body"] is None for card in dialog.event_cards))
            self.assertIsNone(dialog.event_cards[1]["body"])
            dialog._toggle_event_card(dialog.event_cards[0])
            original = [row["name_label"] for row in dialog.item_rows]
            nickname_chip = dialog.item_rows[0]["recipient_buttons"][0]
            nickname_chip.copy()
            self.assertEqual(root.clipboard_get(), "А")
            self.assertEqual(nickname_chip.itemcget(nickname_chip._feedback_text, "state"), "normal")
            copy_job = nickname_chip._feedback_after_id
            self.assertEqual([row["item"]["name"] for row in dialog.item_rows], ["Щит", "Амулет", "Меч"])
            packed_rows = dialog.item_rows[0]["frame"].master.pack_slaves()[-3:]
            self.assertEqual(packed_rows, [row["frame"] for row in dialog.item_rows])
            dialog._toggle_event_card(dialog.event_cards[1])
            self.assertIsNone(dialog.event_cards[0]["body"])
            self.assertFalse(original[0].winfo_exists())
            self.assertFalse(nickname_chip.winfo_exists())
            self.assertNotIn(copy_job, root.tk.call("after", "info"))
            self.assertTrue(dialog.event_cards[1]["expanded"])
            self.assertEqual(dialog.event_cards[0]["frame"].cget("highlightbackground"), BORDER)
            self.assertEqual(dialog.event_cards[1]["frame"].cget("highlightbackground"), ACCENT)
            dialog._toggle_event_card(dialog.event_cards[1])
            self.assertFalse(dialog.item_rows)
            self.assertTrue(all(card["body"] is None for card in dialog.event_cards))
            dialog.destroy()
            root.update_idletasks()
        finally:
            root.destroy()

    def test_history_is_newest_first_and_counts_unique_participants(self):
        root = tk.Tk()
        root.withdraw()
        try:
            first = {
                "id": "first", "created_at": "2026-10-11T12:00:00+03:00",
                "events": [{"name": "Поле боя", "timestamp": "11-10-2026 13:00:00 (UTC-4)",
                            "participants": ["Игрок", "Б"], "items": [
                                {"name": "Меч", "quantity": 1, "divisible": False,
                                 "allocations": [{"participant": "Игрок", "quantity": 1}]},
                            ]}],
            }
            second = deepcopy(first)
            second.update(id="second", created_at="2026-10-12T12:00:00+03:00")
            duplicate_participants = deepcopy(second["events"][0])
            duplicate_participants["participants"] = ["ИГРОК", "В"]
            second["events"].append(duplicate_participants)
            oldest = deepcopy(first)
            oldest.update(id="oldest", created_at="2026-10-10T12:00:00+03:00")
            dialog = DistributionReportDialog(root, [oldest, first, second], ui_scale=0.8)
            self.assertEqual([card["report"]["id"] for card in dialog.report_cards], ["second", "first", "oldest"])
            self.assertEqual(
                [(card["frame"].grid_info()["row"], card["frame"].grid_info()["column"])
                 for card in dialog.report_cards], [(0, 0), (0, 1), (1, 0)],
            )
            self.assertEqual(dialog.report_cards[0]["title"].cget("text"), "Распределение 12.10")
            self.assertEqual(dialog.report_cards[-1]["frame"].grid_info()["pady"], 0)
            self.assertEqual(dialog.report_cards[0]["participant_count"], 3)
            self.assertEqual(dialog.report_cards[0]["item_count"], 2)
            self.assertEqual(dialog.report_cards[0]["event_count"], 2)
            self.assertIn("12.10.2026", dialog.report_cards[0]["date"].cget("text"))
            dialog.destroy()
            direct = DistributionReportDialog(
                root, [second], ui_scale=1, initial_report=second,
                on_load_reports=lambda: [first, second],
            )
            self.assertIs(direct.current_report, second)
            direct.back_button.invoke()
            self.assertEqual([card["report"]["id"] for card in direct.report_cards], ["second", "first"])
            direct.destroy()
            empty = DistributionReportDialog(root, [], ui_scale=1)
            self.assertFalse(empty.report_cards)
            self.assertFalse(empty.event_cards)
            self.assertEqual(empty.rows_frame.winfo_children()[0].cget("text"), "Распределений пока нет")
            empty.destroy()
            root.update_idletasks()
        finally:
            root.destroy()

    def test_main_window_distributes_independently_and_restores_draft_on_rescale(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            participant_store = ParticipantStore(directory / "data.json")
            participant_store.save([Participant("А", bm=100), Participant("Б", bm=50)])
            draw_store = DrawLogStore(directory / "draw_log.json")
            distribution_store = MassDistributionStore(directory / "mass_distribution_log.json")
            with (
                patch("syndicate.application.ParticipantStore", return_value=participant_store),
                patch("syndicate.application.DrawLogStore", return_value=draw_store),
                patch("syndicate.application.MassDistributionStore", return_value=distribution_store),
                patch.object(WheelApp, "_draw_wheel"),
                patch.object(WheelApp, "_show_main_window"),
                patch.object(WheelApp, "_calculate_ui_scale", return_value=1.0),
            ):
                app = WheelApp()
                try:
                    app.show_mass_distribution()
                    self.assertTrue(app.participants_panel.distribution_header_controls.winfo_manager())
                    self.assertTrue(app.participants_panel.distribution_header_separator.winfo_manager())
                    self.assertEqual(app.participants_panel.last_win_header_labels[0].cget("text"), "УЧАСТИЯ / ВЫДАЧИ")
                    panel = app.mass_distribution_panel
                    panel.set_events(parse_distribution_events(
                        "Кровь\t6\tПоле боя\t12-10-2026 13:20:48 (UTC-4)"
                    ))
                    for option in ("bg", "fg", "font", "pady", "highlightbackground", "activebackground"):
                        self.assertEqual(panel.distribute_button.cget(option), app.spin_button.cget(option))
                    card = panel.event_cards[0]
                    panel._toggle_event(card)
                    app.participants_panel.apply_distribution_participants_text(card["event"].key, "А, Б")
                    panel._toggle_divisible_item("Кровь")
                    self.assertEqual(participant_store.divisible_items, ["Кровь"])

                    app._rebuild_scaled_ui(0.8)
                    panel = app.mass_distribution_panel
                    card = panel.event_cards[0]
                    self.assertEqual(card["participant_names"], ["А", "Б"])
                    self.assertTrue(card["expanded"])
                    self.assertEqual(panel.divisible_items, ["Кровь"])
                    self.assertEqual(
                        app.participants_panel.distribution_participant_names(card["event"].key),
                        ["А", "Б"],
                    )
                    with patch("syndicate.mass_distribution_ui.DistributionReportDialog") as direct_dialog:
                        panel._distribute()
                    self.assertIn("initial_report", direct_dialog.call_args.kwargs)
                    self.assertFalse(panel.events)
                    self.assertFalse(panel.event_cards)
                    self.assertIsNone(app.participants_panel._active_distribution_event_key)
                    log = distribution_store.load()
                    self.assertEqual(len(log["reports"]), 1)
                    item = log["reports"][0]["events"][0]["items"][0]
                    self.assertTrue(item["divisible"])
                    self.assertEqual(sum(row["quantity"] for row in item["allocations"]), 6)
                    self.assertFalse(draw_store.path.exists())
                    self.assertEqual(app.rotation, 0)
                    self.assertEqual(app.distribution_statistics_for("Поле боя", "А"), (1, 1))
                    self.assertEqual(app.distribution_statistics_for(None, "А"), (1, 1))

                    report_dialog = DistributionReportDialog(app, log["reports"], ui_scale=0.8)
                    self.assertFalse(report_dialog.item_rows)
                    report_dialog._show_report(report_dialog.report_cards[0]["report"])
                    self.assertFalse(report_dialog.item_rows)
                    report_dialog._toggle_event_card(report_dialog.event_cards[0])
                    self.assertEqual([row["item"]["name"] for row in report_dialog.item_rows], ["Кровь"])
                    self.assertEqual(sum(allocation["quantity"] for row in report_dialog.item_rows for allocation in row["allocations"]), 6)
                    self.assertEqual({allocation["participant"] for allocation in report_dialog.item_rows[0]["allocations"]}, {"А", "Б"})
                    report_dialog.destroy()
                    settings_dialog = ItemSettingsDialog(app, ["Кровь"], panel._set_divisible_items, ui_scale=0.8)
                    settings_dialog.rows[0]["delete"]._activate()
                    self.assertEqual(participant_store.divisible_items, [])
                    settings_dialog.destroy()
                    app.show_draw_mode()
                    self.assertFalse(app.participants_panel.distribution_header_controls.winfo_manager())
                    self.assertEqual(app.participants_panel.last_win_header_labels[0].cget("text"), "ПОСЛЕДНЯЯ ПОБЕДА")
                    app.update_idletasks()
                finally:
                    app.destroy()


if __name__ == "__main__":
    unittest.main()
