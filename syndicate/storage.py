"""Portable JSON persistence for participants, settings, and draw history."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .models import DrawResult, NicknameCorrection, Participant, clean_nickname, nickname_lookup_key
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
    ) -> None:
        influence = self.bm_influence_percent
        if bm_influence_percent is not None:
            influence = min(100.0, max(0.0, bm_influence_percent))
        corrections = (
            list(nickname_corrections)
            if nickname_corrections is not None
            else list(self.nickname_corrections)
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
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
        self.bm_influence_percent = influence
        self.nickname_corrections = corrections


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
            if winner and reward and timestamp:
                results.append(DrawResult(winner, reward, timestamp))
        return results

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
            "version": 1,
            "draws": [
                {
                    "winner": item.winner,
                    "reward": item.reward,
                    "timestamp": item.timestamp,
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
