import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from syndicate.application import WheelApp
from syndicate.models import (
    DrawResult,
    LastWinInfo,
    Participant,
    format_draw_timestamp,
    format_draws_ago,
    last_win_statistics,
)
from syndicate.storage import DrawLogStore


class DrawLogStoreTests(unittest.TestCase):
    def test_appends_unicode_results_without_losing_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            store = DrawLogStore(path)
            first = DrawResult(
                "лена",
                "Книга запретных знаний мастера",
                "2026-08-14T12:30:00+03:00",
                ("лена", "Другой игрок"),
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
            self.assertEqual(raw["version"], 3)
            self.assertEqual(raw["draws"][0]["winner"], "лена")
            self.assertEqual(
                raw["draws"][0]["participants"],
                ["лена", "Другой игрок"],
            )
            self.assertEqual(raw["draws"][1]["winner"], "ネリエル")

    def test_loads_legacy_results_without_participant_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "draws": [
                            {
                                "winner": "Player",
                                "reward": "Prize",
                                "timestamp": "2026-01-01T20:00:00+03:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                DrawLogStore(path).load(),
                [
                    DrawResult(
                        "Player",
                        "Prize",
                        "2026-01-01T20:00:00+03:00",
                        penalty_applied=False,
                    )
                ],
            )

    def test_migrates_legacy_log_to_current_version_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "draws": [
                            {
                                "winner": "Player",
                                "reward": "Prize",
                                "timestamp": "2026-01-01T20:00:00+03:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = DrawLogStore(path)

            self.assertTrue(store.migrate())

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 3)
            self.assertEqual(payload["draws"][0]["participants"], [])
            self.assertFalse(payload["draws"][0]["penalty_applied"])
            self.assertFalse(store.migrate())

    def test_version_two_records_become_neutral_during_migration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "draws": [
                            {
                                "winner": "Player",
                                "reward": "Prize",
                                "timestamp": "2026-01-01T20:00:00+03:00",
                                "participants": ["Player", "Other"],
                                "penalty_applied": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = DrawLogStore(path)

            self.assertTrue(store.migrate())

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 3)
            self.assertFalse(payload["draws"][0]["penalty_applied"])
            self.assertFalse(store.load()[0].penalty_applied)

    def test_migration_does_not_overwrite_malformed_log(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            original = '{"version": 1, "draws": "invalid"}'
            path.write_text(original, encoding="utf-8")

            with self.assertRaises(ValueError):
                DrawLogStore(path).migrate()

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_migration_preserves_unknown_fields_and_unreadable_rows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "custom": "keep me",
                        "draws": [
                            {
                                "winner": "Player",
                                "reward": "Prize",
                                "timestamp": "2026-01-01T20:00:00+03:00",
                                "custom_draw_field": 42,
                            },
                            "unreadable row",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            DrawLogStore(path).migrate()

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["custom"], "keep me")
            self.assertEqual(payload["draws"][0]["custom_draw_field"], 42)
            self.assertEqual(payload["draws"][0]["participants"], [])
            self.assertFalse(payload["draws"][0]["penalty_applied"])
            self.assertEqual(payload["draws"][1], "unreadable row")

    def test_migration_repairs_old_multi_winner_participant_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            participants = ["A", "B", "C", "D"]
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "draws": [
                            {
                                "winner": winner,
                                "reward": "Prize",
                                "timestamp": "2026-10-02T20:53:43+03:00",
                                "participants": participants,
                            }
                            for winner in ("A", "B", "C")
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = DrawLogStore(path)

            self.assertTrue(store.migrate())

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["participants"] for item in payload["draws"]],
                [
                    ["A", "B", "C", "D"],
                    ["B", "C", "D"],
                    ["C", "D"],
                ],
            )
            self.assertTrue(
                all(
                    not item["penalty_applied"]
                    for item in payload["draws"]
                )
            )
            self.assertFalse(store.migrate())

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

    def test_round_can_be_saved_as_neutral_for_penalty_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draw_log.json"
            result = DrawResult(
                "Player",
                "Prize",
                "2026-10-02T20:00:00+03:00",
                ("Player", "Other"),
                penalty_applied=False,
            )

            DrawLogStore(path).append(result)

            self.assertEqual(DrawLogStore(path).load(), [result])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(payload["draws"][0]["penalty_applied"])

    def test_application_commits_each_winner_as_its_own_row(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = DrawLogStore(Path(folder) / "draw_log.json")
            state = SimpleNamespace(
                _reward_ocr_generation=1,
                _roll_prize_image=None,
                _pending_draw_results=[],
                _roll_logged=False,
                _roll_slots=[
                    Participant("Pjanka"),
                    Participant("XmelON"),
                    Participant("Asper"),
                ],
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
            self.assertTrue(
                all(
                    item.participants == ("Pjanka", "XmelON", "Asper")
                    for item in results
                )
            )

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

    def test_last_win_statistics_counts_each_history_row(self) -> None:
        results = [
            DrawResult("A", "Prize 1", "2026-09-01T20:00:00+03:00"),
            DrawResult("B", "Prize 2", "2026-09-04T20:00:00+03:00"),
            DrawResult("C", "Prize 2", "2026-09-04T20:00:00+03:00"),
            DrawResult("A", "Prize 3", "2026-09-09T20:00:00+03:00"),
            DrawResult("D", "Prize 3", "2026-09-09T20:00:00+03:00"),
        ]

        statistics = last_win_statistics(results, date(2026, 9, 10))

        self.assertEqual(statistics["A"], LastWinInfo(2, 1))
        self.assertEqual(statistics["D"], LastWinInfo(1, 1))
        self.assertEqual(statistics["B"], LastWinInfo(4, 6))
        self.assertEqual(statistics["C"], LastWinInfo(3, 6))
        self.assertNotIn("never", statistics)

    def test_last_win_statistics_keep_name_case_significant(self) -> None:
        results = [
            DrawResult("XmelON", "Prize 1", "2026-09-08T20:00:00+03:00"),
            DrawResult("Xmelon", "Prize 2", "2026-09-09T20:00:00+03:00"),
        ]

        statistics = last_win_statistics(results, date(2026, 9, 10))

        self.assertEqual(statistics["XmelON"], LastWinInfo(2, 2))
        self.assertEqual(statistics["Xmelon"], LastWinInfo(1, 1))

    def test_last_win_age_counts_only_draws_attended_by_that_player(self) -> None:
        results = [
            DrawResult(
                "A",
                "Prize 1",
                "2026-09-01T20:00:00+03:00",
                ("A", "B"),
            ),
            DrawResult(
                "B",
                "Prize 2",
                "2026-09-02T20:00:00+03:00",
                ("B", "C"),
            ),
            DrawResult(
                "C",
                "Prize 3",
                "2026-09-03T20:00:00+03:00",
                ("A", "C"),
            ),
            DrawResult(
                "D",
                "Prize 4",
                "2026-09-04T20:00:00+03:00",
                ("C", "D"),
            ),
        ]

        statistics = last_win_statistics(results, date(2026, 9, 5))

        self.assertEqual(statistics["A"], LastWinInfo(2, 4))
        self.assertEqual(statistics["B"], LastWinInfo(1, 3))
        self.assertEqual(statistics["C"], LastWinInfo(2, 2))
        self.assertEqual(statistics["D"], LastWinInfo(1, 1))

    def test_legacy_last_win_age_keeps_global_count(self) -> None:
        results = [
            DrawResult("A", "Old prize", "2026-09-01T20:00:00+03:00"),
            DrawResult(
                "B",
                "New prize",
                "2026-09-02T20:00:00+03:00",
                ("B", "C"),
            ),
        ]

        statistics = last_win_statistics(results, date(2026, 9, 3))

        self.assertEqual(statistics["A"], LastWinInfo(2, 2))

    def test_draw_age_uses_correct_russian_word_form(self) -> None:
        self.assertEqual(format_draws_ago(1), "1 розыгрыш назад")
        self.assertEqual(format_draws_ago(2), "2 розыгрыша назад")
        self.assertEqual(format_draws_ago(5), "5 розыгрышей назад")
        self.assertEqual(format_draws_ago(11), "11 розыгрышей назад")
        self.assertEqual(format_draws_ago(21), "21 розыгрыш назад")


if __name__ == "__main__":
    unittest.main()
