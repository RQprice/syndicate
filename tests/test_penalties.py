import unittest
import tkinter as tk
from types import SimpleNamespace

from syndicate.application import WheelApp
from syndicate.models import DrawResult, LastWinInfo, Participant, PenaltySettings
from syndicate.penalties import (
    WinnerPenaltyStatus,
    advance_penalty_statuses,
    format_probability_with_penalty,
    format_remaining_draws,
    probabilities_with_penalties,
    winner_penalty_statuses,
)
from syndicate.theme import DANGER


class WinnerPenaltyTests(unittest.TestCase):
    def test_completed_spin_advances_penalties_before_the_next_spin(self) -> None:
        settings = PenaltySettings()
        statuses = {"A": WinnerPenaltyStatus(0.25, 4)}

        after_first = advance_penalty_statuses(
            statuses,
            ("A", "B", "C"),
            "B",
            settings,
        )
        after_second = advance_penalty_statuses(
            after_first,
            ("A", "C"),
            "C",
            settings,
        )

        self.assertEqual(after_first["A"], WinnerPenaltyStatus(0.4, 3))
        self.assertEqual(after_second["A"], WinnerPenaltyStatus(0.6, 2))
        self.assertEqual(after_first["B"], WinnerPenaltyStatus(0.25, 4))

    def test_penalty_recovers_only_from_the_players_own_participation(self) -> None:
        results = [
            DrawResult(
                "A",
                "Prize 1",
                "2026-10-01T18:00:00+03:00",
                ("A", "B", "C"),
            ),
            DrawResult(
                "B",
                "Prize 2",
                "2026-10-02T18:00:00+03:00",
                ("B", "C"),
            ),
            DrawResult(
                "C",
                "Prize 3",
                "2026-10-03T18:00:00+03:00",
                ("A", "B", "C"),
            ),
        ]

        statuses = winner_penalty_statuses(results, PenaltySettings())

        self.assertEqual(statuses["A"], WinnerPenaltyStatus(0.4, 3))
        self.assertEqual(statuses["B"], WinnerPenaltyStatus(0.4, 3))
        self.assertEqual(statuses["C"], WinnerPenaltyStatus(0.25, 4))

    def test_multi_winner_series_treats_each_spin_as_a_separate_draw(self) -> None:
        results = [
            DrawResult(
                "A",
                "Prize 1",
                "2026-10-01T18:00:00+03:00",
                ("A", "B", "C"),
            ),
            DrawResult(
                "B",
                "Prize 2",
                "2026-10-02T18:00:00+03:00",
                ("B", "C"),
            ),
            DrawResult(
                "C",
                "Prize 2",
                "2026-10-02T18:00:00+03:00",
                ("C",),
            ),
        ]

        statuses = winner_penalty_statuses(results, PenaltySettings())

        self.assertEqual(statuses["A"], WinnerPenaltyStatus(0.25, 4))
        self.assertEqual(statuses["B"], WinnerPenaltyStatus(0.25, 4))
        self.assertEqual(statuses["C"], WinnerPenaltyStatus(0.25, 4))

    def test_penalty_disappears_after_configured_number_of_participations(self) -> None:
        results = [
            DrawResult("A", "Prize", "1", ("A", "B")),
            DrawResult("B", "Prize", "2", ("A", "B")),
            DrawResult("B", "Prize", "3", ("A", "B")),
            DrawResult("B", "Prize", "4", ("A", "B")),
            DrawResult("B", "Prize", "5", ("A", "B")),
        ]

        statuses = winner_penalty_statuses(results, PenaltySettings())

        self.assertNotIn("A", statuses)

    def test_disabled_penalties_have_no_display_status(self) -> None:
        results = [DrawResult("A", "Prize", "1", ("A", "B"))]

        statuses = winner_penalty_statuses(
            results,
            PenaltySettings(enabled=False),
        )

        self.assertEqual(statuses, {})

    def test_neutral_draw_neither_recovers_nor_creates_penalty(self) -> None:
        results = [
            DrawResult("A", "Prize", "1", ("A", "B")),
            DrawResult(
                "B",
                "Neutral prize",
                "2",
                ("A", "B"),
                penalty_applied=False,
            ),
        ]

        statuses = winner_penalty_statuses(results, PenaltySettings())

        self.assertEqual(statuses["A"], WinnerPenaltyStatus(0.25, 4))
        self.assertNotIn("B", statuses)

    def test_legacy_wins_without_participants_do_not_create_penalties(self) -> None:
        results = [
            DrawResult("A", "Old prize", "2026-08-01T18:00:00+03:00"),
            DrawResult("B", "Old prize", "2026-08-02T18:00:00+03:00"),
        ]

        statuses = winner_penalty_statuses(results, PenaltySettings())

        self.assertEqual(statuses, {})

    def test_new_draw_can_start_penalty_after_legacy_history(self) -> None:
        results = [
            DrawResult("A", "Old prize", "2026-08-01T18:00:00+03:00"),
            DrawResult(
                "B",
                "New prize",
                "2026-10-01T18:00:00+03:00",
                ("A", "B"),
            ),
        ]

        statuses = winner_penalty_statuses(results, PenaltySettings())

        self.assertNotIn("A", statuses)
        self.assertEqual(statuses["B"], WinnerPenaltyStatus(0.25, 4))

    def test_remaining_draw_caption_uses_russian_word_forms(self) -> None:
        self.assertEqual(format_remaining_draws(1), "1 розыгрыш с участием")
        self.assertEqual(format_remaining_draws(2), "2 розыгрыша с участием")
        self.assertEqual(format_remaining_draws(5), "5 розыгрышей с участием")

    def test_penalty_coefficient_reduces_and_renormalizes_probability(self) -> None:
        participants = [Participant("A"), Participant("B")]

        probabilities = probabilities_with_penalties(
            participants,
            [0.5, 0.5],
            {"A": 0.25},
        )

        self.assertEqual(probabilities, [0.2, 0.8])
        self.assertEqual(
            format_probability_with_penalty(probabilities[0], 0.25),
            "20.00% (×0.25)",
        )

    def test_draw_workflow_uses_penalized_probabilities(self) -> None:
        participants = [Participant("A", bm=100), Participant("B", bm=100)]
        state = SimpleNamespace(
            _roll_slots=participants,
            _roll_penalty_coefficients={"A": 0.25},
            bm_influence_percent=0.0,
            participants=participants,
        )

        probabilities = WheelApp._mapped_roll_probabilities(
            state,
            participants,
        )

        self.assertEqual(probabilities, [0.2, 0.8])


class PenaltyDisplayTests(unittest.TestCase):
    @staticmethod
    def _label_texts(widget: tk.Misc) -> set[str]:
        texts: set[str] = set()
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                texts.add(str(child.cget("text")))
            texts.update(PenaltyDisplayTests._label_texts(child))
        return texts

    def test_active_penalty_is_red_and_added_to_last_win_tooltip(self) -> None:
        app = WheelApp()
        app.withdraw()
        app.update_idletasks()
        try:
            panel = app.participants_panel
            self.assertTrue(panel.apply_penalty_var.get())
            name = "PenaltyDisplayTestPlayer"
            result = DrawResult(
                name,
                "Test reward",
                "2026-10-01T18:00:00+03:00",
                (name, "Other"),
            )
            panel._last_win_statistics[name] = LastWinInfo(1, 0)
            panel._last_win_results[name] = result
            panel._penalty_statuses[name] = WinnerPenaltyStatus(0.4, 3)
            panel._add_row(name, False, 1.0, scroll_to_end=False)
            row = panel.rows[-1]
            primary = row["last_win_primary"]
            self.assertIsInstance(primary, tk.Label)
            assert isinstance(primary, tk.Label)

            self.assertEqual(primary.cget("fg"), DANGER)

            panel._show_last_win_tooltip(
                row,
                SimpleNamespace(x_root=0, y_root=0),
            )
            tooltip = panel._last_win_tooltip
            self.assertIsNotNone(tooltip)
            assert tooltip is not None
            labels = self._label_texts(tooltip)
            self.assertIn("Test reward", labels)
            self.assertIn("Коэффициент: 0.4", labels)
            self.assertIn(
                "До снятия штрафа: 3 розыгрыша с участием",
                labels,
            )

            app.participants = [
                Participant(name, True, 1.0),
                Participant("Other", True, 1.0),
            ]
            panel._penalty_statuses = {
                name: WinnerPenaltyStatus(0.4, 3),
            }
            app._draw_wheel()
            wheel_labels = {
                str(app.wheel_canvas.itemcget(item, "text"))
                for item in app.wheel_canvas.find_withtag("labels")
            }
            self.assertIn("28.57% (×0.4)", wheel_labels)

            app._request_wheel_redraw = lambda: None
            panel.apply_penalty_var.set(False)
            app._draw_wheel()
            neutral_labels = {
                str(app.wheel_canvas.itemcget(item, "text"))
                for item in app.wheel_canvas.find_withtag("labels")
            }
            self.assertIn("50.00%", neutral_labels)
            self.assertFalse(any("×" in text for text in neutral_labels))
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
