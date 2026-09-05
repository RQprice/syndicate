import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app import DrawLogStore, DrawResult, WheelApp, format_draw_timestamp


class DrawLogStoreTests(unittest.TestCase):
    def test_appends_unicode_results_without_losing_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            store = DrawLogStore(path)
            first = DrawResult(
                "лена",
                "Книга запретных знаний мастера",
                "2026-08-14T12:30:00+03:00",
            )
            second = DrawResult(
                "ネリエル",
                "Клановый сундук",
                "2026-08-14T12:45:00+03:00",
            )

            store.append(first)
            store.append(second)

            self.assertEqual(store.load(), [first, second])
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], 1)
            self.assertEqual(raw["draws"][0]["winner"], "лена")
            self.assertEqual(raw["draws"][1]["winner"], "ネリエル")

    def test_missing_log_is_an_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = DrawLogStore(Path(folder) / "draw_log.json")

            self.assertEqual(store.load(), [])

    def test_appends_multiple_winners_as_separate_history_rows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = DrawLogStore(Path(folder) / "draw_log.json")
            timestamp = "2026-08-15T20:00:00+03:00"
            results = [
                DrawResult("Pjanka", "Шлем Кари", timestamp),
                DrawResult("XmelON", "Шлем Кари", timestamp),
                DrawResult("Asper", "Шлем Кари", timestamp),
            ]

            store.append_many(results)

            self.assertEqual(store.load(), results)

    def test_application_commits_each_winner_as_its_own_row(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = DrawLogStore(Path(folder) / "draw_log.json")
            state = SimpleNamespace(
                _reward_ocr_generation=1,
                _roll_prize_image=None,
                _pending_draw_results=[],
                _roll_logged=False,
                _reward_ocr_pending=False,
                _refresh_result_preparation_state=Mock(),
                draw_log_store=store,
                participants_panel=SimpleNamespace(
                    refresh_history_dialog=Mock()
                ),
            )

            WheelApp._begin_reward_recognition(state, ["Pjanka", "XmelON"])
            WheelApp._commit_pending_draw_result(state)

            results = store.load()
            self.assertEqual([item.winner for item in results], ["Pjanka", "XmelON"])
            self.assertTrue(
                all(item.reward == "Награда не указана" for item in results)
            )
            self.assertEqual(results[0].timestamp, results[1].timestamp)

    def test_remove_at_deletes_only_the_selected_record(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = DrawLogStore(Path(folder) / "draw_log.json")
            first = DrawResult("Player", "Prize", "2026-01-01T20:00:00+03:00")
            second = DrawResult("Player", "Prize", "2026-01-01T20:01:00+03:00")
            store.append(first)
            store.append(second)

            removed = store.remove_at(1)

            self.assertEqual(removed, second)
            self.assertEqual(store.load(), [first])

    def test_timestamp_has_readable_day_month_year_format(self) -> None:
        self.assertEqual(
            format_draw_timestamp("2026-01-01T20:00:00+03:00"),
            "01.01.2026 20:00",
        )


if __name__ == "__main__":
    unittest.main()
