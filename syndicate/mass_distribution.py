"""Independent, auditable allocation of event rewards with persistent fair shares."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json
import random
import re
import secrets
import uuid

from .models import clean_nickname, nickname_lookup_key


@dataclass(frozen=True)
class DistributionItem:
    name: str
    quantity: int


@dataclass(frozen=True)
class DistributionEvent:
    name: str
    timestamp: str
    items: tuple[DistributionItem, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.name, self.timestamp)


@dataclass(frozen=True)
class DistributionRequest:
    event: DistributionEvent
    participants: tuple[str, ...]


def event_datetime(timestamp: str) -> datetime:
    """Read exported day-month-year dates with explicit UTC offsets or ISO dates."""
    match = re.fullmatch(
        r"(\d{2}[-.]\d{2}[-.]\d{4} \d{2}:\d{2}:\d{2}) \(UTC([+-]\d{1,2})(?::(\d{2}))?\)",
        timestamp.strip(),
    )
    try:
        if match:
            offset_hours = int(match[2])
            offset_minutes = int(match[3] or 0)
            if offset_minutes >= 60:
                raise ValueError
            offset = timedelta(
                hours=offset_hours,
                minutes=offset_minutes * (-1 if match[2].startswith("-") else 1),
            )
            date = datetime.strptime(match[1].replace(".", "-"), "%d-%m-%Y %H:%M:%S")
            return date.replace(tzinfo=timezone(offset)).astimezone(timezone.utc)
        date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError
        return date.astimezone(timezone.utc)
    except ValueError as error:
        raise ValueError(f"Не удалось прочитать дату события: {timestamp}") from error


def event_identity(event: DistributionEvent) -> tuple[str, str]:
    return nickname_lookup_key(event.name), event_datetime(event.timestamp).isoformat()


def empty_distribution_log() -> dict:
    return {"version": 1, "reports": []}


def _distribution_reports(log: dict) -> list[dict]:
    if not isinstance(log, dict) or log.get("version") != 1:
        raise ValueError("Неподдерживаемый формат истории массового распределения.")
    reports = log.get("reports")
    if not isinstance(reports, list):
        raise ValueError("Некорректная история массового распределения.")
    return reports


def distribution_balances(log: dict) -> dict:
    """Fully replay allocations for recovery/audits, never resetting corrupt history."""
    reports = _distribution_reports(log)
    balances: dict = {}
    seen: set[tuple[str, str]] = set()
    try:
        for report in reports:
            if report["algorithm"] not in ("fair-share-v1", "fair-share-v2", "fair-share-v3", "fair-share-v4") or not report["events"]:
                raise ValueError
            if not isinstance(report["id"], str) or not report["id"]:
                raise ValueError
            event_datetime(report["created_at"])
            int(report["random_seed"])
            for event in report["events"]:
                identity = event_identity(DistributionEvent(event["name"], event["timestamp"], ()))
                if identity in seen:
                    raise ValueError
                seen.add(identity)
                participants = event["participants"]
                keys = [nickname_lookup_key(name) for name in participants]
                if not keys or not all(keys) or len(set(keys)) != len(keys):
                    raise ValueError
                ledger = balances.setdefault(identity[0], {"overall": {}, "items": {}})
                if not event["items"]:
                    raise ValueError
                for item in event["items"]:
                    quantity = item["quantity"]
                    divisible = item["divisible"]
                    if type(quantity) is not int or quantity < 1 or type(divisible) is not bool:
                        raise ValueError
                    item_key = nickname_lookup_key(item["name"])
                    if not item_key:
                        raise ValueError
                    item_ledger = ledger["items"].setdefault(item_key, {})
                    _credit(ledger["overall"], keys)
                    _credit(item_ledger, keys)
                    allocations = item["allocations"]
                    if not allocations or sum(row["quantity"] for row in allocations) != quantity:
                        raise ValueError
                    recipients: set[str] = set()
                    if not divisible and len(allocations) != 1:
                        raise ValueError
                    if divisible and report["algorithm"] == "fair-share-v2":
                        recipient_count = _equal_recipient_count(quantity, len(keys))
                        if len(allocations) != recipient_count or any(
                            row["quantity"] != quantity // recipient_count for row in allocations
                        ):
                            raise ValueError
                    if divisible and report["algorithm"] == "fair-share-v3":
                        if sorted(row["quantity"] for row in allocations) != sorted(
                            _split_portions(quantity, len(keys))
                        ):
                            raise ValueError
                    if divisible and report["algorithm"] == "fair-share-v4":
                        if sorted(row["quantity"] for row in allocations) != sorted(
                            _split_portions(quantity, len(allocations))
                        ):
                            raise ValueError
                    for row in allocations:
                        key = nickname_lookup_key(row["participant"])
                        count = row["quantity"]
                        if key not in keys or key in recipients or type(count) is not int or count < 1:
                            raise ValueError
                        recipients.add(key)
                        share = Fraction(count, quantity)
                        ledger["overall"][key] -= share
                        item_ledger[key] -= share
        return balances
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError("История массового распределения повреждена. Распределение остановлено.") from error


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deserialize_distribution_balances(raw: dict) -> dict:
    """Read exact canonical fractions and validate the saved ledger's structure."""
    def read_accounts(accounts: dict) -> dict[str, Fraction]:
        if not isinstance(accounts, dict):
            raise ValueError("Некорректный баланс.")
        result = {}
        for name, value in accounts.items():
            if not isinstance(name, str) or not name or nickname_lookup_key(name) != name:
                raise ValueError("Некорректное имя в балансе.")
            if not isinstance(value, str):
                raise ValueError("Баланс должен содержать точные дроби.")
            fraction = Fraction(value)
            if str(fraction) != value:
                raise ValueError("Некорректная дробь в балансе.")
            result[name] = fraction
        if sum(result.values(), Fraction()) != 0:
            raise ValueError("Нарушен баланс долей.")
        return result

    if not isinstance(raw, dict):
        raise ValueError("Некорректный баланс.")
    balances = {}
    for name, ledger in raw.items():
        if not isinstance(name, str) or not name or nickname_lookup_key(name) != name:
            raise ValueError("Некорректное событие в балансе.")
        if not isinstance(ledger, dict) or not isinstance(ledger.get("items"), dict):
            raise ValueError("Некорректный баланс события.")
        overall = read_accounts(ledger["overall"])
        items = {}
        totals = {key: Fraction() for key in overall}
        for item, accounts in ledger["items"].items():
            if not isinstance(item, str) or not item or nickname_lookup_key(item) != item:
                raise ValueError("Некорректный предмет в балансе.")
            values = read_accounts(accounts)
            for key, value in values.items():
                if key not in totals:
                    raise ValueError("Неизвестный участник в балансе предмета.")
                totals[key] += value
            items[item] = values
        if totals != overall:
            raise ValueError("Баланс предметов не совпадает с общим балансом.")
        balances[name] = {"overall": overall, "items": items}
    return balances


def _make_balance_cache(reports: list[dict], balances: dict) -> dict:
    ledger = {
        name: {
            "overall": {key: str(value) for key, value in accounts["overall"].items()},
            "items": {item: {key: str(value) for key, value in values.items()}
                      for item, values in accounts["items"].items()},
        }
        for name, accounts in balances.items()
    }
    return {
        "version": 1, "algorithm": "fair-share-v1",
        "history_sha256": _json_digest(reports),
        "ledger_sha256": _json_digest(ledger),
        "ledger": ledger,
    }


def load_distribution_balances(log: dict) -> dict:
    """Use an intact history-bound snapshot, or recover by replaying allocations."""
    reports = _distribution_reports(log)
    cache = log.get("balance_cache")
    try:
        if not isinstance(cache, dict) or type(cache.get("version")) is not int or cache["version"] != 1:
            raise ValueError
        if cache.get("algorithm") != "fair-share-v1":
            raise ValueError
        if cache.get("history_sha256") != _json_digest(reports):
            raise ValueError
        if cache.get("ledger_sha256") != _json_digest(cache["ledger"]):
            raise ValueError
        return deserialize_distribution_balances(cache["ledger"])
    except (KeyError, TypeError, AttributeError, ValueError, ZeroDivisionError):
        return distribution_balances(log)


def _credit(ledger: dict[str, Fraction], keys: list[str]) -> None:
    entitlement = Fraction(1, len(keys))
    for key in keys:
        ledger[key] = ledger.get(key, Fraction()) + entitlement


def _equal_recipient_count(quantity: int, participant_count: int) -> int:
    """Legacy v2 policy: largest divisor not exceeding the participant count."""
    return next(count for count in range(min(quantity, participant_count), 0, -1)
                if quantity % count == 0)


def _split_portions(quantity: int, participant_count: int) -> list[int]:
    """Smallest common portion fitting the roster, then a positive smaller tail."""
    portion = (quantity + participant_count - 1) // participant_count
    recipient_count = (quantity + portion - 1) // portion
    return [portion] * (recipient_count - 1) + [quantity - portion * (recipient_count - 1)]


def _fair_split_portions(
    quantity: int, candidates: list[str], overall: dict[str, Fraction],
    item_ledger: dict[str, Fraction], rng: random.Random,
) -> list[int]:
    """Choose group size by the smallest post-award imbalance, not roster size."""
    overall_prefix = [Fraction()]
    item_prefix = [Fraction()]
    for key in candidates:
        overall_prefix.append(overall_prefix[-1] + overall[key])
        item_prefix.append(item_prefix[-1] + item_ledger[key])
    best_score = None
    best_plans = []
    seen_portions = set()
    for limit in range(1, min(quantity, len(candidates)) + 1):
        portion = (quantity + limit - 1) // limit
        if portion in seen_portions:
            continue
        seen_portions.add(portion)
        full_count = (quantity - 1) // portion
        remainder = quantity - portion * full_count
        full_share, tail_share = Fraction(portion, quantity), Fraction(remainder, quantity)
        square_cost = full_count * full_share ** 2 + tail_share ** 2
        # Unchanged players and pre-award squares cancel between plans. Prefix
        # sums evaluate each group in O(1), keeping the whole search O(players).
        score = (
            square_cost - 2 * (full_share * overall_prefix[full_count]
                               + tail_share * overall[candidates[full_count]]),
            square_cost - 2 * (full_share * item_prefix[full_count]
                               + tail_share * item_ledger[candidates[full_count]]),
        )
        plan = (portion, full_count, remainder)
        if best_score is None or score < best_score:
            best_score, best_plans = score, [plan]
        elif score == best_score:
            best_plans.append(plan)
    portion, full_count, remainder = rng.choice(best_plans) if len(best_plans) > 1 else best_plans[0]
    return [portion] * full_count + [remainder]


def _allocate(
    overall: dict[str, Fraction],
    item_ledger: dict[str, Fraction],
    keys: list[str],
    quantity: int,
    divisible: bool,
    rng: random.Random,
) -> Counter:
    candidates = list(keys)
    # Stable sorting preserves this shuffle only for equal balance priorities.
    rng.shuffle(candidates)
    candidates.sort(key=lambda key: (overall[key], item_ledger[key]), reverse=True)
    portions = _fair_split_portions(quantity, candidates, overall, item_ledger, rng) if divisible else [quantity]
    recipients = candidates[:len(portions)]
    for key, portion in zip(recipients, portions):
        cost = Fraction(portion, quantity)
        overall[key] -= cost
        item_ledger[key] -= cost
    return Counter(dict(zip(recipients, portions)))


def prepare_distribution(
    requests: list[DistributionRequest],
    divisible_items: list[str],
    log: dict,
    *,
    seed: int | None = None,
    balances: dict | None = None,
) -> tuple[dict, dict]:
    """Build an all-or-nothing batch; optional balances must be previously validated."""
    if not requests:
        raise ValueError("Выберите события и предметы для распределения.")
    # Storage may supply an already validated snapshot to avoid loading it twice.
    balances = load_distribution_balances(log) if balances is None else deepcopy(balances)
    processed = {
        event_identity(DistributionEvent(event["name"], event["timestamp"], ()))
        for report in log["reports"] for event in report["events"]
    }
    for request in requests:
        event = request.event
        identity = event_identity(event)
        if identity in processed:
            raise ValueError(f"Событие уже распределено: {event.name} · {event.timestamp}")
        processed.add(identity)
        keys = [nickname_lookup_key(name) for name in request.participants]
        if not keys or not all(keys):
            raise ValueError(f"Необходимо выбрать участников: {event.name} · {event.timestamp}")
        if len(set(keys)) != len(keys):
            raise ValueError("В списке участников есть одинаковые имена. Исправьте их перед распределением.")
        if not event.items or any(type(item.quantity) is not int or item.quantity < 1 or not item.name.strip() for item in event.items):
            raise ValueError(f"Нет корректных предметов для события: {event.name}")

    seed = secrets.randbits(128) if seed is None else seed
    rng = random.Random(seed)
    divisible_keys = {nickname_lookup_key(name) for name in divisible_items}
    report = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "algorithm": "fair-share-v4",
        "random_seed": str(seed),
        "divisible_items": list(divisible_items),
        "events": [],
    }
    # Process older occurrences first even when the export is newest-first.
    for source_position, request in sorted(
        enumerate(requests),
        key=lambda pair: (event_datetime(pair[1].event.timestamp), nickname_lookup_key(pair[1].event.name)),
    ):
        event = request.event
        names = {nickname_lookup_key(name): clean_nickname(name) for name in request.participants}
        keys = sorted(names)
        ledger = balances.setdefault(nickname_lookup_key(event.name), {"overall": {}, "items": {}})
        before = {key: ledger["overall"].get(key, Fraction()) for key in keys}
        # Repeated rows of one reward type represent one combined stack.
        combined: dict[str, DistributionItem] = {}
        for item in event.items:
            key = nickname_lookup_key(item.name)
            old = combined.get(key)
            combined[key] = DistributionItem(old.name if old else item.name, item.quantity + (old.quantity if old else 0))
        pools = [combined[key] for key in sorted(combined)]
        source_positions = {key: index for index, key in enumerate(combined)}
        rng.shuffle(pools)
        event_report = {
            "name": event.name,
            "timestamp": event.timestamp,
            "source_position": source_position,
            "participants": [names[key] for key in keys],
            "items": [],
            "balance_before": {names[key]: str(value) for key, value in before.items()},
        }
        for item in pools:
            item_key = nickname_lookup_key(item.name)
            item_ledger = ledger["items"].setdefault(item_key, {})
            item_before = {key: item_ledger.get(key, Fraction()) for key in keys}
            _credit(ledger["overall"], keys)
            _credit(item_ledger, keys)
            divisible = item_key in divisible_keys
            allocations = _allocate(ledger["overall"], item_ledger, keys, item.quantity, divisible, rng)
            recipients = list(allocations)
            rng.shuffle(recipients)
            if divisible:
                # Keep the smaller remainder last while shuffling equal portions.
                recipients.sort(key=lambda key: allocations[key], reverse=True)
            event_report["items"].append({
                "name": item.name,
                "quantity": item.quantity,
                "source_position": source_positions[item_key],
                "divisible": divisible,
                "allocations": [{"participant": names[key], "quantity": allocations[key]} for key in recipients],
                "balance_before": {names[key]: str(item_before[key]) for key in keys},
                "balance_after": {names[key]: str(item_ledger[key]) for key in keys},
            })
        event_report["balance_after"] = {names[key]: str(ledger["overall"][key]) for key in keys}
        report["events"].append(event_report)
    updated = deepcopy(log)
    updated["reports"].append(report)
    updated["balance_cache"] = _make_balance_cache(updated["reports"], balances)
    return report, updated


def ordered_report_events(report: dict) -> list[dict]:
    """Keep source presentation order separate from chronological ledger replay."""
    return [event for _index, event in sorted(
        enumerate(report["events"]),
        key=lambda pair: pair[1].get("source_position", pair[0]),
    )]


def ordered_report_items(event: dict) -> list[dict]:
    """Present the imported order while retaining calculation order in the journal."""
    return [item for _index, item in sorted(
        enumerate(event["items"]),
        key=lambda pair: pair[1].get("source_position", pair[0]),
    )]


def distribution_statistics(reports: list[dict]) -> dict[str, dict[str, tuple[int, int]]]:
    """Count attended occurrences and reward allocations per participant/event type."""
    statistics: dict[str, dict[str, tuple[int, int]]] = {}
    for report in reports:
        for event in report["events"]:
            event_statistics = statistics.setdefault(nickname_lookup_key(event["name"]), {})
            for name in event["participants"]:
                key = nickname_lookup_key(name)
                attended, received = event_statistics.get(key, (0, 0))
                event_statistics[key] = (attended + 1, received)
            for item in event["items"]:
                for allocation in item["allocations"]:
                    key = nickname_lookup_key(allocation["participant"])
                    attended, received = event_statistics[key]
                    event_statistics[key] = (attended, received + 1)
    return statistics
