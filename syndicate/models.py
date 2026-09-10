"""Application data models and presentation-independent formatting helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Participant:
    name: str
    enabled: bool = True
    bm: float = 0.0


@dataclass(frozen=True)
class NicknameCorrection:
    recognized: str
    replacement: str


@dataclass(frozen=True)
class DrawResult:
    winner: str
    reward: str
    timestamp: str


@dataclass(frozen=True)
class LastWinInfo:
    draws_ago: int
    days_ago: int | None


@dataclass(frozen=True)
class RecordedWheelFrame:
    rotation: float
    names: tuple[str, ...]
    probabilities: tuple[float, ...]
    winner_index: int | None = None


def clean_nickname(name: str) -> str:
    return " ".join(name.strip().split())


def nickname_lookup_key(name: str) -> str:
    return clean_nickname(name).casefold()


def format_bm(value: float) -> str:
    """Format BM for quick visual scanning while keeping decimals if present."""

    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    whole, fraction = f"{value:.2f}".rstrip("0").rstrip(".").split(".")
    return f"{int(whole):,}".replace(",", " ") + f".{fraction}"


def format_draw_timestamp(value: str) -> str:
    """Format an ISO draw timestamp without changing its recorded wall time."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return value
    return parsed.strftime("%d.%m.%Y %H:%M")


def draw_result_date(value: str) -> date | None:
    """Return the recorded local calendar date from an ISO timestamp."""

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (AttributeError, TypeError, ValueError):
        return None


def last_win_statistics(
    results: list[DrawResult],
    today: date | None = None,
) -> dict[str, LastWinInfo]:
    """Return the latest win age for each exact, whitespace-cleaned name.

    The most recently appended history entry is draw number one. Each entry
    is counted independently, even when several entries share a timestamp.
    """

    reference_day = today or datetime.now().astimezone().date()
    statistics: dict[str, LastWinInfo] = {}
    for draws_ago, result in enumerate(reversed(results), start=1):
        key = clean_nickname(result.winner)
        if not key or key in statistics:
            continue
        won_on = draw_result_date(result.timestamp)
        days_ago = (
            max(0, (reference_day - won_on).days)
            if won_on is not None
            else None
        )
        statistics[key] = LastWinInfo(
            draws_ago,
            days_ago,
        )
    return statistics


def format_draws_ago(value: int) -> str:
    remainder_100 = value % 100
    remainder_10 = value % 10
    if remainder_10 == 1 and remainder_100 != 11:
        noun = "розыгрыш"
    elif remainder_10 in (2, 3, 4) and remainder_100 not in (12, 13, 14):
        noun = "розыгрыша"
    else:
        noun = "розыгрышей"
    return f"{value} {noun} назад"


def parse_bm(value: str) -> float:
    """Parse both plain and visually grouped BM values."""

    compact = value.replace("\u00a0", "").replace(" ", "").strip()
    return float(compact.replace(",", ".") or "0")


def sort_participants_by_bm(
    participants: list[Participant],
) -> list[Participant]:
    """Return participants ordered by BM from highest to lowest."""

    return sorted(participants, key=lambda participant: participant.bm, reverse=True)
