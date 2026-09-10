import time
import unittest
from unittest.mock import Mock

from syndicate.application import WheelApp
from syndicate.models import Participant


class MultiWinnerRollTests(unittest.TestCase):
    def test_multiple_prizes_choose_unique_winners_and_cancel_restores_pool(self) -> None:
        app = WheelApp()
        app.withdraw()
        try:
            app.participants = [
                Participant("A", True, 100),
                Participant("B", True, 200),
                Participant("C", True, 300),
                Participant("D", True, 400),
            ]
            app.participants_panel.flush_auto_save = Mock()
            app.participants_panel.set_editing_enabled = Mock()
            app.prize_quantity_control.set_value(3)
            app.MULTI_SPIN_DURATION_SECONDS = 0.04
            app.MULTI_WINNER_HOLD_SECONDS = 0.01
            app.SECTOR_TRANSITION_SECONDS = 0.02
            app.VIDEO_FPS = 4
            app.DISC_ANTIALIAS_SCALE = 1
            recognized_winners: list[str] = []
            recorded_winners: list[str] = []
            app._begin_reward_recognition = (
                lambda winners: recognized_winners.extend(winners)
            )
            app._begin_video_generation = (
                lambda winners: recorded_winners.extend(winners)
            )

            app._start_spin()
            deadline = time.monotonic() + 5
            while app.spinning and time.monotonic() < deadline:
                app.update()
                time.sleep(0.002)

            self.assertFalse(app.spinning)
            self.assertEqual(len(app._roll_winners), 3)
            self.assertEqual(len(set(app._roll_winners)), 3)
            self.assertEqual(recognized_winners, app._roll_winners)
            self.assertEqual(recorded_winners, app._roll_winners)
            self.assertEqual(app.result_var.get(), " | ".join(app._roll_winners))
            original_winner_order = list(app._roll_winners)
            bm_by_name = {
                participant.name: participant.bm
                for participant in app.participants
            }
            expected_bm_order = sorted(
                original_winner_order,
                key=bm_by_name.__getitem__,
                reverse=True,
            )
            self.assertEqual(app.result_sort_button.winfo_manager(), "place")
            app.result_sort_button.invoke()
            self.assertEqual(app.result_var.get(), " | ".join(expected_bm_order))
            self.assertEqual(app._roll_winners, original_winner_order)
            self.assertEqual(recorded_winners, original_winner_order)
            self.assertEqual(
                sum(value == 0 for value in app._roll_probabilities or []),
                3,
            )
            self.assertAlmostEqual(sum(app._roll_probabilities or []), 1.0)
            self.assertTrue(
                any(frame.winner_index is not None for frame in app._video_frames)
            )
            self.assertGreater(
                len({frame.probabilities for frame in app._video_frames}),
                3,
            )

            app._cancel_roll_result()
            app.update_idletasks()
            self.assertIsNone(app._roll_slots)
            self.assertEqual(
                [participant.name for participant in app.active_participants],
                ["A", "B", "C", "D"],
            )
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
