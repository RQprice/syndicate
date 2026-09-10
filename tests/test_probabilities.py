import unittest

from syndicate.models import Participant
from syndicate.probabilities import (
    participant_probabilities,
    participant_weights,
    weighted_random_index,
)


class ParticipantProbabilityTests(unittest.TestCase):
    def test_probability_is_split_into_equal_and_bm_pools(self) -> None:
        guild = [
            Participant("Low", bm=100),
            Participant("Middle", bm=200),
            Participant("High", bm=300),
        ]
        draw = [guild[1], guild[2]]

        probabilities = participant_probabilities(draw, 30, guild)

        self.assertAlmostEqual(probabilities[0], 0.45)
        self.assertAlmostEqual(probabilities[1], 0.55)
        self.assertAlmostEqual(sum(probabilities), 1.0)

    def test_normalization_uses_the_whole_guild(self) -> None:
        guild = [
            Participant("Guild minimum", bm=100_000),
            Participant("First", bm=210_000),
            Participant("Second", bm=211_000),
            Participant("Guild maximum", bm=300_000),
        ]
        draw = [guild[1], guild[2]]

        probabilities = participant_probabilities(draw, 30, guild)

        first_normalized = (210_000 - 100_000) / (300_000 - 100_000)
        second_normalized = (211_000 - 100_000) / (300_000 - 100_000)
        normalized_total = first_normalized + second_normalized
        self.assertAlmostEqual(
            probabilities[0], 0.35 + 0.30 * first_normalized / normalized_total
        )
        self.assertAlmostEqual(
            probabilities[1], 0.35 + 0.30 * second_normalized / normalized_total
        )

    def test_zero_normalized_sum_falls_back_to_equal_probabilities(self) -> None:
        guild = [
            Participant("First", bm=100),
            Participant("Second", bm=100),
            Participant("Higher guild member", bm=300),
        ]
        draw = guild[:2]

        self.assertEqual(participant_probabilities(draw, 30, guild), [0.5, 0.5])

    def test_zero_weight_is_supported_at_one_hundred_percent_influence(self) -> None:
        weights = participant_weights(
            [Participant("Minimum", bm=100), Participant("Maximum", bm=300)],
            100,
        )

        self.assertEqual(weights, [0.0, 1.0])
        self.assertEqual(weighted_random_index(weights), 1)


if __name__ == "__main__":
    unittest.main()
