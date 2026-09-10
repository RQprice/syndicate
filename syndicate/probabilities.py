"""BM-based probability calculation and secure weighted selection."""
from __future__ import annotations

import math
import secrets

from .models import Participant
from .theme import DEFAULT_BM_INFLUENCE_PERCENT


def participant_weights(
    participants: list[Participant],
    influence_percent: float = DEFAULT_BM_INFLUENCE_PERCENT,
    normalization_population: list[Participant] | None = None,
) -> list[float]:
    """Split probability into equal and normalized-BM pools.

    BM values are min-max normalized against the whole supplied population,
    while the BM probability pool is shared only by the draw participants.
    """
    if not participants:
        return []

    population = normalization_population or participants
    population_values = [max(0.0, participant.bm) for participant in population]
    minimum = min(population_values)
    maximum = max(population_values)
    spread = maximum - minimum
    influence = (
        min(100.0, max(0.0, influence_percent)) / 100.0
        if math.isfinite(influence_percent)
        else 0.0
    )
    participant_count = len(participants)

    if math.isclose(spread, 0.0):
        normalized_values = [0.0] * participant_count
    else:
        normalized_values = [
            min(
                1.0,
                max(0.0, (max(0.0, participant.bm) - minimum) / spread),
            )
            for participant in participants
        ]

    normalized_total = sum(normalized_values)
    if math.isclose(normalized_total, 0.0):
        return [1.0 / participant_count] * participant_count

    equal_share = (1.0 - influence) / participant_count
    return [
        equal_share + influence * normalized / normalized_total
        for normalized in normalized_values
    ]


def participant_probabilities(
    participants: list[Participant],
    influence_percent: float = DEFAULT_BM_INFLUENCE_PERCENT,
    normalization_population: list[Participant] | None = None,
) -> list[float]:
    weights = participant_weights(
        participants, influence_percent, normalization_population
    )
    total = sum(weights)
    return [weight / total for weight in weights] if total else []


def weighted_random_index(weights: list[float]) -> int:
    """Choose an index using OS-provided randomness and the supplied weights."""
    if not weights or any(weight < 0 for weight in weights):
        raise ValueError("Weights must be non-negative")
    total = sum(weights)
    if total <= 0:
        raise ValueError("At least one weight must be positive")
    threshold = (secrets.randbits(53) / (1 << 53)) * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if threshold < cumulative:
            return index
    return len(weights) - 1
