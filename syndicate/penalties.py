"""Participation-based winner penalty state derived from draw history."""
from __future__ import annotations

from dataclasses import dataclass

from .models import DrawResult, Participant, PenaltySettings, clean_nickname


@dataclass(frozen=True)
class WinnerPenaltyStatus:
    coefficient: float
    remaining_participations: int


def winner_penalty_statuses(
    results: list[DrawResult],
    settings: PenaltySettings,
) -> dict[str, WinnerPenaltyStatus]:
    """Return active penalties after replaying saved draws in order.

    Every result row is a separate wheel spin. Multi-winner series therefore
    advance through their successively smaller participant pools one by one.
    """

    if not settings.enabled or len(settings.chance_steps) < 2:
        return {}

    progress: dict[str, int] = {}
    for penalty_applied, winners, participants in _draws(results):
        if not penalty_applied:
            continue
        # Version 1 history has no participant snapshot.  It cannot tell us
        # whether recovery already happened, so it must not create a penalty.
        if not participants:
            continue
        for name in participants - winners:
            if name in progress:
                progress[name] += 1
        for winner in winners:
            progress[winner] = 0

    full_chance_index = len(settings.chance_steps) - 1
    return {
        name: WinnerPenaltyStatus(
            coefficient=settings.chance_steps[participations],
            remaining_participations=full_chance_index - participations,
        )
        for name, participations in progress.items()
        if participations < full_chance_index
    }


def format_penalty_coefficient(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def probabilities_with_penalties(
    participants: list[Participant],
    weights: list[float],
    coefficients: dict[str, float],
) -> list[float]:
    """Apply per-name penalty multipliers and normalize the result."""

    if len(participants) != len(weights):
        raise ValueError("Participants and weights must have the same length")
    adjusted = [
        weight * coefficients.get(clean_nickname(participant.name), 1.0)
        for participant, weight in zip(participants, weights)
    ]
    total = sum(adjusted)
    return [value / total for value in adjusted] if total > 0 else []


def advance_penalty_statuses(
    statuses: dict[str, WinnerPenaltyStatus],
    participants: tuple[str, ...],
    winner: str,
    settings: PenaltySettings,
) -> dict[str, WinnerPenaltyStatus]:
    """Advance penalties by one completed, penalty-enabled wheel spin."""

    if not settings.enabled or len(settings.chance_steps) < 2:
        return {}

    updated = dict(statuses)
    winner_name = clean_nickname(winner)
    participant_names = {
        name
        for raw_name in participants
        if (name := clean_nickname(raw_name))
    }
    full_chance_index = len(settings.chance_steps) - 1
    for name in participant_names - {winner_name}:
        status = updated.get(name)
        if status is None:
            continue
        remaining = status.remaining_participations - 1
        if remaining <= 0:
            updated.pop(name, None)
            continue
        step_index = full_chance_index - remaining
        updated[name] = WinnerPenaltyStatus(
            settings.chance_steps[step_index],
            remaining,
        )
    if winner_name:
        updated[winner_name] = WinnerPenaltyStatus(
            settings.chance_steps[0],
            full_chance_index,
        )
    return updated


def format_probability_with_penalty(
    probability: float,
    coefficient: float,
) -> str:
    text = f"{probability * 100:.2f}%"
    if coefficient < 1.0:
        text += f" (×{format_penalty_coefficient(coefficient)})"
    return text


def format_remaining_draws(value: int) -> str:
    remainder_100 = value % 100
    remainder_10 = value % 10
    if remainder_10 == 1 and remainder_100 != 11:
        noun = "розыгрыш"
    elif remainder_10 in (2, 3, 4) and remainder_100 not in (12, 13, 14):
        noun = "розыгрыша"
    else:
        noun = "розыгрышей"
    return f"{value} {noun} с участием"


def _draws(
    results: list[DrawResult],
) -> list[tuple[bool, set[str], set[str]]]:
    draws: list[tuple[bool, set[str], set[str]]] = []
    for result in results:
        participants = {
            name
            for raw_name in result.participants
            if (name := clean_nickname(raw_name))
        }
        winner = clean_nickname(result.winner)
        winners = {winner} if winner else set()
        draws.append((result.penalty_applied, winners, participants))
    return draws
