"""Portable JSON persistence for participants, settings, and draw history."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .models import (
    DrawResult,
    NicknameCorrection,
    Participant,
    PenaltySettings,
    clean_nickname,
    nickname_lookup_key,
)
from .platform import application_directory
from .theme import DEFAULT_BM_INFLUENCE_PERCENT


class ParticipantStore:
    """Store portable user data beside the source or packaged executable."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = application_directory() / "data.json"
        self.path = path
        self.bm_influence_percent = DEFAULT_BM_INFLUENCE_PERCENT
        self.nickname_corrections: list[NicknameCorrection] = []
        self.penalty_settings = PenaltySettings()

    def load(self) -> list[Participant]:
        if not self.path.exists():
            self.save([])
            return []

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            influence = float(
                raw.get("bm_influence_percent", DEFAULT_BM_INFLUENCE_PERCENT)
            )
            if not math.isfinite(influence):
                influence = DEFAULT_BM_INFLUENCE_PERCENT
            self.bm_influence_percent = min(100.0, max(0.0, influence))
            corrections: dict[str, NicknameCorrection] = {}
            raw_corrections = raw.get("nickname_corrections", [])
            if isinstance(raw_corrections, dict):
                raw_corrections = [
                    {"recognized": recognized, "replacement": replacement}
                    for recognized, replacement in raw_corrections.items()
                ]
            if isinstance(raw_corrections, list):
                for item in raw_corrections:
                    if not isinstance(item, dict):
                        continue
                    recognized = clean_nickname(str(item.get("recognized", "")))
                    replacement = clean_nickname(str(item.get("replacement", "")))
                    key = nickname_lookup_key(recognized)
                    if key and replacement:
                        corrections[key] = NicknameCorrection(
                            recognized, replacement
                        )
            self.nickname_corrections = list(corrections.values())
            self.penalty_settings = self._load_penalty_settings(
                raw.get("winner_penalty")
            )
            items = raw.get("participants", [])
            result = [
                Participant(
                    str(item["name"]).strip(),
                    False,
                    max(0.0, float(item.get("bm", 0.0))),
                )
                for item in items
                if str(item.get("name", "")).strip()
            ]
            return result
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def save(
        self,
        participants: list[Participant],
        bm_influence_percent: float | None = None,
        nickname_corrections: list[NicknameCorrection] | None = None,
        penalty_settings: PenaltySettings | None = None,
    ) -> None:
        influence = self.bm_influence_percent
        if bm_influence_percent is not None:
            influence = min(100.0, max(0.0, bm_influence_percent))
        corrections = (
            list(nickname_corrections)
            if nickname_corrections is not None
            else list(self.nickname_corrections)
        )
        penalty = (
            penalty_settings
            if penalty_settings is not None
            else self.penalty_settings
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bm_influence_percent": influence,
            "participants": [
                {"name": item.name, "bm": item.bm} for item in participants
            ],
            "nickname_corrections": [
                {
                    "recognized": correction.recognized,
                    "replacement": correction.replacement,
                }
                for correction in corrections
            ],
            "winner_penalty": {
                "enabled": penalty.enabled,
                "recovery_participations": penalty.recovery_participations,
                "chance_steps": list(penalty.chance_steps),
            },
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
        self.bm_influence_percent = influence
        self.nickname_corrections = corrections
        self.penalty_settings = penalty

    @staticmethod
    def _load_penalty_settings(raw: object) -> PenaltySettings:
        default = PenaltySettings()
        if not isinstance(raw, dict):
            return default
        enabled = raw.get("enabled")
        raw_steps = raw.get("chance_steps")
        if not isinstance(enabled, bool) or not isinstance(raw_steps, list):
            return default
        try:
            steps = tuple(float(value) for value in raw_steps)
        except (TypeError, ValueError):
            return default
        if (
            len(steps) < 2
            or any(not math.isfinite(value) or not 0 < value <= 1 for value in steps)
            or not math.isclose(steps[-1], 1.0)
            or any(current < previous for previous, current in zip(steps, steps[1:]))
        ):
            return default
        recovery = raw.get("recovery_participations", len(steps) - 1)
        if not isinstance(recovery, int) or recovery != len(steps) - 1:
            return default
        return PenaltySettings(enabled=enabled, chance_steps=steps)


class DrawLogStore:
    """Keep confirmed draw results in a portable JSON file beside the app."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or application_directory() / "draw_log.json"

    def load(self) -> list[DrawResult]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("draws", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            raise ValueError("Некорректный формат журнала розыгрышей.")

        results: list[DrawResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            winner = str(item.get("winner", "")).strip()
            reward = str(item.get("reward", "")).strip()
            timestamp = str(item.get("timestamp", "")).strip()
            raw_participants = item.get("participants", [])
            participants = (
                tuple(
                    name
                    for value in raw_participants
                    if (name := clean_nickname(str(value)))
                )
                if isinstance(raw_participants, list)
                else ()
            )
            penalty_applied = item.get("penalty_applied", False)
            if not isinstance(penalty_applied, bool):
                penalty_applied = False
            if winner and reward and timestamp:
                results.append(
                    DrawResult(
                        winner,
                        reward,
                        timestamp,
                        participants,
                        penalty_applied,
                    )
                )
        return results

    def migrate(self) -> bool:
        """Upgrade legacy fields and repair old multi-winner participant pools."""

        if not self.path.exists():
            return False
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("draws", []), list):
            raise ValueError("Некорректный формат журнала розыгрышей.")
        version = raw.get("version", 1)
        if version not in (1, 2, 3):
            raise ValueError(f"Неподдерживаемая версия журнала: {version}")
        migrated = dict(raw)
        migrated["version"] = 3
        migrated["draws"] = [
            {
                **item,
                "participants": item.get("participants", []),
                # До версии 3 поле не отражало явный выбор пользователя:
                # старую историю делаем нейтральной для расчёта штрафов.
                "penalty_applied": (
                    item.get("penalty_applied", False)
                    if version == 3
                    and isinstance(item.get("penalty_applied", False), bool)
                    else False
                ),
            }
            if isinstance(item, dict)
            else item
            for item in raw.get("draws", [])
        ]
        migrated["draws"] = self._normalize_multi_winner_rounds(
            migrated["draws"]
        )
        if migrated == raw:
            return False
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(migrated, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return True

    @staticmethod
    def _normalize_multi_winner_rounds(items: list[object]) -> list[object]:
        normalized: list[object] = []
        series_timestamp = ""
        original_participants: tuple[str, ...] = ()
        previous_winners: set[str] = set()
        for raw_item in items:
            if not isinstance(raw_item, dict):
                normalized.append(raw_item)
                series_timestamp = ""
                original_participants = ()
                previous_winners.clear()
                continue
            item = dict(raw_item)
            timestamp = str(item.get("timestamp", ""))
            raw_participants = item.get("participants", [])
            participants = (
                tuple(str(name) for name in raw_participants)
                if isinstance(raw_participants, list)
                else ()
            )
            continuing_series = (
                bool(participants)
                and timestamp == series_timestamp
                and participants == original_participants
            )
            if not continuing_series:
                series_timestamp = timestamp
                original_participants = participants
                previous_winners = set()
            if participants:
                item["participants"] = [
                    name
                    for name in participants
                    if clean_nickname(name) not in previous_winners
                ]
                winner = clean_nickname(str(item.get("winner", "")))
                if winner:
                    previous_winners.add(winner)
            normalized.append(item)
        return normalized

    def append(self, result: DrawResult) -> None:
        self.append_many([result])

    def append_many(self, new_results: list[DrawResult]) -> None:
        if not new_results:
            return
        results = self.load()
        results.extend(new_results)
        self._write(results)

    def remove_at(self, index: int) -> DrawResult:
        results = self.load()
        if not 0 <= index < len(results):
            raise IndexError("Запись розыгрыша не найдена.")
        removed = results.pop(index)
        self._write(results)
        return removed

    def _write(self, results: list[DrawResult]) -> None:
        payload = {
            "version": 3,
            "draws": [
                {
                    "winner": item.winner,
                    "reward": item.reward,
                    "timestamp": item.timestamp,
                    "participants": list(item.participants),
                    "penalty_applied": item.penalty_applied,
                }
                for item in results
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
