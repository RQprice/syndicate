import json
from pathlib import Path
import tempfile
import unittest
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import random
from unittest.mock import patch

from syndicate.mass_distribution import (
    DistributionEvent, DistributionItem, DistributionRequest,
    distribution_balances, empty_distribution_log, prepare_distribution,
    load_distribution_balances,
    ordered_report_events, ordered_report_items,
    _allocate, _split_portions,
)
from syndicate.models import Participant
from syndicate.storage import MassDistributionStore, ParticipantStore


def request(index=1, names=("А", "Б", "В"), items=None, event_name="Поле боя"):
    return DistributionRequest(
        DistributionEvent(
            event_name, f"2026-10-12T13:{index:02d}:00-04:00",
            tuple(items or [DistributionItem("Броня", 1)]),
        ),
        tuple(names),
    )


class FairDistributionTests(unittest.TestCase):
    def test_divisible_stacks_use_common_portions_with_smaller_remainder(self):
        for quantity, participant_count, portions in (
            (13, 6, [3, 3, 3, 3, 1]), (13, 7, [2, 2, 2, 2, 2, 2, 1]),
            (10, 6, [2, 2, 2, 2, 2]), (5, 3, [2, 2, 1]), (12, 5, [3, 3, 3, 3]),
            (100, 6, [17, 17, 17, 17, 17, 15]), (6, 6, [1] * 6),
            (4, 6, [1] * 4), (1, 6, [1]), (7, 6, [2, 2, 2, 1]), (10, 1, [10]),
        ):
            with self.subTest(quantity=quantity, participants=participant_count):
                names = tuple(f"Игрок {index}" for index in range(participant_count))
                report, log = prepare_distribution(
                    [request(names=names, items=[DistributionItem("Кровь", quantity)])],
                    ["Кровь"], empty_distribution_log(), seed=123,
                )
                allocations = report["events"][0]["items"][0]["allocations"]
                self.assertEqual([row["quantity"] for row in allocations], portions)
                self.assertLessEqual(len(allocations), participant_count)
                self.assertEqual(sum(row["quantity"] for row in allocations), quantity)
                self.assertEqual(len({row["participant"] for row in allocations}), len(portions))
                self.assertEqual(load_distribution_balances(log), distribution_balances(log))
                for row in allocations:
                    self.assertEqual(
                        load_distribution_balances(log)["поле боя"]["overall"][row["participant"].casefold()],
                        Fraction(1, participant_count) - Fraction(row["quantity"], quantity),
                    )

    def test_larger_portions_go_to_players_with_higher_existing_balances(self):
        names = tuple(f"Игрок {index}" for index in range(6))
        earlier, log = prepare_distribution(
            [request(names=names, items=[DistributionItem(f"Броня {index}", 1) for index in range(4)])],
            [], empty_distribution_log(), seed=4,
        )
        prior_recipients = {item["allocations"][0]["participant"] for item in earlier["events"][0]["items"]}
        starved = set(names) - prior_recipients
        self.assertEqual(len(starved), 2)
        report, updated = prepare_distribution(
            [request(2, names=names, items=[DistributionItem("Кровь", 13)])], ["Кровь"], log, seed=9,
        )
        allocations = report["events"][0]["items"][0]["allocations"]
        self.assertEqual(starved, {row["participant"] for row in allocations})
        self.assertEqual([row["quantity"] for row in allocations], [7, 6])
        self.assertEqual(load_distribution_balances(updated), distribution_balances(updated))

    def test_balance_guided_split_compensates_excluded_players_across_events(self):
        names = tuple(f"Игрок {index}" for index in range(6))
        log = empty_distribution_log()
        received = Counter()
        previously_excluded = set()
        group_sizes = set()
        for index in range(1, 7):
            report, log = prepare_distribution(
                [request(index, names=names, items=[DistributionItem("Кровь", 10)])],
                ["Кровь"], log, seed=index,
            )
            allocations = report["events"][0]["items"][0]["allocations"]
            recipients = {row["participant"] for row in allocations}
            self.assertTrue(previously_excluded <= recipients)
            previously_excluded = set(names) - recipients
            group_sizes.add(len(allocations))
            self.assertEqual([row["quantity"] for row in allocations], _split_portions(10, len(allocations)))
            for row in allocations:
                received[row["participant"]] += row["quantity"]
        self.assertLessEqual(max(received.values()) - min(received.values()), 2)
        self.assertEqual(sum(received.values()), 60)
        self.assertGreater(len(group_sizes), 1)
        self.assertEqual(load_distribution_balances(log), distribution_balances(log))

    def test_balance_guided_split_chooses_the_lowest_post_award_imbalance(self):
        sample_rng = random.Random(55)
        for participant_count in range(1, 7):
            for quantity in range(1, 21):
                with self.subTest(participants=participant_count, quantity=quantity):
                    keys = [str(index) for index in range(participant_count)]
                    overall = {key: Fraction(sample_rng.randrange(-6, 7), 3) for key in keys}
                    item_ledger = {key: Fraction(sample_rng.randrange(-6, 7), 4) for key in keys}
                    previous_overall, previous_items = dict(overall), dict(item_ledger)
                    ranked = sorted(keys, key=lambda key: (overall[key], item_ledger[key]), reverse=True)
                    scores = []
                    for limit in range(1, min(quantity, participant_count) + 1):
                        shares = {key: Fraction(portion, quantity)
                                  for key, portion in zip(ranked, _split_portions(quantity, limit))}
                        scores.append((
                            sum((overall[key] - shares.get(key, 0)) ** 2 for key in keys),
                            sum((item_ledger[key] - shares.get(key, 0)) ** 2 for key in keys),
                        ))
                    allocations = _allocate(overall, item_ledger, keys, quantity, True, random.Random(5))
                    actual_score = (sum(value ** 2 for value in overall.values()),
                                    sum(value ** 2 for value in item_ledger.values()))
                    self.assertEqual(actual_score, min(scores))
                    self.assertEqual(sum(allocations.values()), quantity)
                    self.assertEqual(list(allocations.values()), _split_portions(quantity, len(allocations)))
                    for key in keys:
                        self.assertEqual(overall[key], previous_overall[key] - Fraction(allocations[key], quantity))
                        self.assertEqual(item_ledger[key], previous_items[key] - Fraction(allocations[key], quantity))

    def test_one_large_allocation_is_only_chosen_when_it_compensates_prior_underpayment(self):
        names = tuple(f"Игрок {index}" for index in range(6))
        earlier, log = prepare_distribution(
            [request(names=names, items=[DistributionItem(f"Броня {index}", 1) for index in range(5)])],
            [], empty_distribution_log(), seed=33,
        )
        rewarded = {item["allocations"][0]["participant"] for item in earlier["events"][0]["items"]}
        starved = set(names) - rewarded
        self.assertEqual(len(starved), 1)
        report, updated = prepare_distribution(
            [request(2, names=names, items=[DistributionItem("Душа", 13)])], ["Душа"], log, seed=33,
        )
        allocations = report["events"][0]["items"][0]["allocations"]
        self.assertEqual(allocations, [{"participant": next(iter(starved)), "quantity": 13}])
        self.assertTrue(all(balance == 0 for balance in load_distribution_balances(updated)["поле боя"]["overall"].values()))

    def test_equal_split_random_ties_are_reproducible_and_roster_order_independent(self):
        names = tuple(f"Игрок {index}" for index in range(6))
        rewards = [DistributionItem("Кровь", 10)]
        first, _ = prepare_distribution([request(names=names, items=rewards)], ["Кровь"], empty_distribution_log(), seed=44)
        reversed_roster, _ = prepare_distribution(
            [request(names=tuple(reversed(names)), items=rewards)], ["Кровь"], empty_distribution_log(), seed=44,
        )
        self.assertEqual(first["events"], reversed_roster["events"])
        excluded = set()
        for seed in range(40):
            report, _ = prepare_distribution([request(names=names, items=rewards)], ["Кровь"], empty_distribution_log(), seed=seed)
            recipients = {row["participant"] for row in report["events"][0]["items"][0]["allocations"]}
            excluded.update(set(names) - recipients)
        self.assertEqual(excluded, set(names))

    def test_previous_unequal_split_history_is_preserved(self):
        _, old_log = prepare_distribution(
            [request(items=[DistributionItem("Кровь", 5)])], ["Кровь"], empty_distribution_log(), seed=3,
        )
        old_log.pop("balance_cache")
        old_report = old_log["reports"][0]
        old_report["algorithm"] = "fair-share-v1"
        old_report["events"][0]["items"][0]["allocations"] = [
            {"participant": name, "quantity": count}
            for name, count in (("А", 2), ("Б", 2), ("В", 1))
        ]
        original = deepcopy(old_log)
        previous_balances = distribution_balances(old_log)
        report, updated = prepare_distribution(
            [request(2, items=[DistributionItem("Кровь", 6)])], ["Кровь"], old_log, seed=3,
        )
        self.assertEqual(report["algorithm"], "fair-share-v4")
        self.assertEqual(updated["reports"][0], original["reports"][0])
        self.assertEqual(old_log, original)
        self.assertEqual({row["quantity"] for row in report["events"][0]["items"][0]["allocations"]}, {2})
        self.assertEqual(load_distribution_balances(updated), previous_balances)
        self.assertEqual(distribution_balances(updated), previous_balances)
        invalid = deepcopy(old_log)
        invalid["reports"][0]["algorithm"] = "fair-share-v2"
        with self.assertRaisesRegex(ValueError, "повреждена"):
            distribution_balances(invalid)

    def test_v2_prime_stack_history_stays_valid_and_overpaid_player_is_not_selected(self):
        names = tuple(f"Игрок {index}" for index in range(6))
        _, old_log = prepare_distribution(
            [request(names=names, items=[DistributionItem("Душа", 13)])], ["Душа"], empty_distribution_log(), seed=1,
        )
        old_log.pop("balance_cache")
        old_report = old_log["reports"][0]
        old_report["algorithm"] = "fair-share-v2"
        old_report["events"][0]["items"][0]["allocations"] = [{"participant": names[0], "quantity": 13}]
        original = deepcopy(old_log)
        previous_balances = distribution_balances(old_log)
        report, updated = prepare_distribution(
            [request(2, names=names, items=[DistributionItem("Душа", 13)])], ["Душа"], old_log, seed=1,
        )
        allocations = report["events"][0]["items"][0]["allocations"]
        self.assertEqual([row["quantity"] for row in allocations], [3, 3, 3, 3, 1])
        self.assertNotIn(names[0], {row["participant"] for row in allocations})
        self.assertEqual(report["events"][0]["balance_before"][names[0]], str(previous_balances["поле боя"]["overall"][names[0].casefold()]))
        self.assertEqual(old_log, original)
        self.assertEqual(updated["reports"][0], original["reports"][0])
        self.assertEqual(load_distribution_balances(updated), distribution_balances(updated))
        invalid = deepcopy(old_log)
        invalid["reports"][0]["algorithm"] = "fair-share-v3"
        with self.assertRaisesRegex(ValueError, "повреждена"):
            distribution_balances(invalid)

    def test_v3_wide_split_history_is_preserved_when_new_group_sizes_are_balance_guided(self):
        names = tuple(f"Игрок {index}" for index in range(6))
        _, old_log = prepare_distribution(
            [request(names=names, items=[DistributionItem("Душа", 13)])], ["Душа"], empty_distribution_log(), seed=5,
        )
        old_log.pop("balance_cache")
        old_report = old_log["reports"][0]
        old_report["algorithm"] = "fair-share-v3"
        original = deepcopy(old_log)
        old_balances = distribution_balances(old_log)
        report, updated = prepare_distribution(
            [request(2, names=names, items=[DistributionItem("Душа", 13)])], ["Душа"], old_log, seed=9,
        )
        self.assertEqual(report["algorithm"], "fair-share-v4")
        self.assertEqual(updated["reports"][0], original["reports"][0])
        self.assertEqual(old_log, original)
        self.assertEqual(report["events"][0]["balance_before"], {
            name: str(old_balances["поле боя"]["overall"][name.casefold()]) for name in names
        })
        self.assertEqual(load_distribution_balances(updated), distribution_balances(updated))

    def test_smaller_remainder_is_compensated_in_future_events(self):
        log = empty_distribution_log()
        received = Counter()
        for index in range(1, 4):
            report, log = prepare_distribution(
                [request(index, items=[DistributionItem("Душа", 5)])], ["Душа"], log, seed=index,
            )
            allocations = report["events"][0]["items"][0]["allocations"]
            self.assertEqual([row["quantity"] for row in allocations], [2, 2, 1])
            for row in allocations:
                received[row["participant"]] += row["quantity"]
        self.assertEqual(set(received.values()), {5})
        self.assertTrue(all(balance == 0 for balance in load_distribution_balances(log)["поле боя"]["overall"].values()))

    def test_cached_balances_and_next_allocations_match_full_replay(self):
        log = empty_distribution_log()
        names = ("А", "Б", "В", "Новый")
        for index in range(1, 19):
            present = names[:3] if index < 10 else names[1:]
            rewards = [DistributionItem("Кровь", 5), DistributionItem("Броня", 1)]
            _, log = prepare_distribution(
                [request(index, names=present, items=rewards, event_name="Поле боя" if index % 2 else "Остров")],
                ["Кровь"] if index % 3 else [], log, seed=index,
            )
            self.assertEqual(load_distribution_balances(log), distribution_balances(log))
        old_log = deepcopy(log)
        old_log.pop("balance_cache")
        cached_report, _ = prepare_distribution([request(19, names=names)], [], log, seed=123)
        replayed_report, _ = prepare_distribution([request(19, names=names)], [], old_log, seed=123)
        self.assertEqual(cached_report["events"], replayed_report["events"])
        self.assertEqual(load_distribution_balances(log), distribution_balances(old_log))

    def test_invalid_or_stale_cache_recovers_from_history(self):
        _, log = prepare_distribution([request()], [], empty_distribution_log(), seed=1)
        expected = distribution_balances(log)
        for cache in (None, {}, {**log["balance_cache"], "version": 2},
                      {**log["balance_cache"], "algorithm": "unknown"},
                      {**log["balance_cache"], "history_sha256": "old"},
                      {**log["balance_cache"], "ledger_sha256": "damaged"}):
            with self.subTest(cache=cache):
                damaged = deepcopy(log)
                damaged["balance_cache"] = cache
                self.assertEqual(load_distribution_balances(damaged), expected)

        for value in ("1/0", 0.1, "1.0", "5"):
            with self.subTest(value=value):
                damaged = deepcopy(log)
                damaged["balance_cache"]["ledger"]["поле боя"]["overall"]["а"] = value
                # Even a matching checksum cannot make malformed fractions valid.
                damaged["balance_cache"]["ledger_sha256"] = hashlib.sha256(json.dumps(
                    damaged["balance_cache"]["ledger"], ensure_ascii=False,
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                self.assertEqual(load_distribution_balances(damaged), expected)

        changed = deepcopy(log)
        event = changed["reports"][0]["events"][0]
        event["participants"] = ["Г" if name == "А" else name for name in event["participants"]]
        for row in event["items"][0]["allocations"]:
            if row["participant"] == "А":
                row["participant"] = "Г"
        self.assertEqual(load_distribution_balances(changed), distribution_balances(changed))
        self.assertIn("г", load_distribution_balances(changed)["поле боя"]["overall"])
        changed["reports"] = []
        self.assertEqual(load_distribution_balances(changed), {})

    def test_report_preserves_source_event_order_without_changing_chronological_replay(self):
        requests = [request(3), request(1), request(2)]
        report, log = prepare_distribution(requests, [], empty_distribution_log(), seed=1)
        self.assertEqual(
            [event["timestamp"] for event in report["events"]],
            [request(index).event.timestamp for index in (1, 2, 3)],
        )
        self.assertEqual(
            [event["timestamp"] for event in ordered_report_events(report)],
            [entry.event.timestamp for entry in requests],
        )
        self.assertTrue(all(balance == 0 for balance in distribution_balances(log)["поле боя"]["overall"].values()))
        legacy_report = {"events": [{"name": "Первое"}, {"name": "Второе"}]}
        self.assertEqual(ordered_report_events(legacy_report), legacy_report["events"])

    def test_report_preserves_imported_item_order_without_reordering_ledger_replay(self):
        items = [DistributionItem("Щит", 1), DistributionItem("Амулет", 1), DistributionItem("Меч", 1)]
        report, log = prepare_distribution([request(items=items)], [], empty_distribution_log(), seed=1)
        event = report["events"][0]
        self.assertEqual([item["name"] for item in ordered_report_items(event)], [item.name for item in items])
        self.assertNotEqual([item["name"] for item in event["items"]], [item.name for item in items])
        self.assertEqual(sum(distribution_balances(log)["поле боя"]["overall"].values()), 0)

    def test_repeated_scarce_item_compensates_previous_non_recipients(self):
        log = empty_distribution_log()
        received = Counter()
        for index in range(1, 31):
            report, log = prepare_distribution([request(index)], [], log, seed=index)
            recipient = report["events"][0]["items"][0]["allocations"][0]["participant"]
            received[recipient] += 1
            counts = [received[name] for name in ("А", "Б", "В")]
            self.assertLessEqual(max(counts) - min(counts), 1)
        self.assertEqual(list(received.values()), [10, 10, 10])
        ledger = distribution_balances(log)["поле боя"]
        self.assertTrue(all(balance == 0 for balance in ledger["overall"].values()))

    def test_prime_stacks_are_split_but_whole_lot_is_not_split(self):
        log = empty_distribution_log()
        received = Counter()
        for index in range(1, 4):
            report, log = prepare_distribution(
                [request(index, items=[DistributionItem("Кровь", 5)])], ["кровь"], log, seed=index,
            )
            allocations = report["events"][0]["items"][0]["allocations"]
            self.assertEqual([row["quantity"] for row in allocations], [2, 2, 1])
            self.assertEqual(sum(row["quantity"] for row in allocations), 5)
            for row in allocations:
                self.assertIs(type(row["quantity"]), int)
                received[row["participant"]] += row["quantity"]
        self.assertEqual(list(received.values()), [5, 5, 5])
        report, _ = prepare_distribution(
            [request(items=[DistributionItem("Кровь", 100)])], [], empty_distribution_log(), seed=7,
        )
        allocations = report["events"][0]["items"][0]["allocations"]
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0]["quantity"], 100)

    def test_equal_bundles_with_different_names_spread_in_one_event(self):
        report, log = prepare_distribution(
            [request(items=[DistributionItem(f"Предмет {index}", 1) for index in range(6)])],
            [], empty_distribution_log(), seed=9,
        )
        counts = Counter(
            item["allocations"][0]["participant"] for item in report["events"][0]["items"]
        )
        self.assertEqual(sorted(counts.values()), [2, 2, 2])
        balances = distribution_balances(log)["поле боя"]["overall"]
        self.assertTrue(all(value == 0 for value in balances.values()))

    def test_random_seed_is_reproducible_and_participant_order_does_not_bias(self):
        first, _ = prepare_distribution([request()], [], empty_distribution_log(), seed=4)
        reversed_roster, _ = prepare_distribution([request(names=("В", "Б", "А"))], [], empty_distribution_log(), seed=4)
        self.assertEqual(first["events"], reversed_roster["events"])
        winners = {
            prepare_distribution([request()], [], empty_distribution_log(), seed=seed)[0]
            ["events"][0]["items"][0]["allocations"][0]["participant"]
            for seed in range(30)
        }
        self.assertEqual(winners, {"А", "Б", "В"})

    def test_absentees_and_other_event_types_do_not_gain_or_spend_credit(self):
        report, log = prepare_distribution([request()], [], empty_distribution_log(), seed=5)
        winner = report["events"][0]["items"][0]["allocations"][0]["participant"]
        before = distribution_balances(log)["поле боя"]["overall"][winner.casefold()]
        present = tuple(name for name in ("А", "Б", "В") if name != winner)
        _, log = prepare_distribution([request(2, names=present)], [], log, seed=6)
        self.assertEqual(distribution_balances(log)["поле боя"]["overall"][winner.casefold()], before)
        _, log = prepare_distribution([request(3, event_name="Другое событие")], [], log, seed=6)
        self.assertEqual(distribution_balances(log)["поле боя"]["overall"][winner.casefold()], before)

    def test_oldest_event_is_processed_first_and_equivalent_timestamp_is_duplicate(self):
        report, log = prepare_distribution([request(2), request(1)], [], empty_distribution_log(), seed=1)
        self.assertEqual(report["events"][0]["timestamp"], request(1).event.timestamp)
        duplicate = DistributionRequest(
            DistributionEvent("ПОЛЕ БОЯ", "12-10-2026 17:01:00 (UTC+0)", (DistributionItem("Броня", 1),)),
            ("А", "Б", "В"),
        )
        with self.assertRaisesRegex(ValueError, "уже распределено"):
            prepare_distribution([duplicate], [], log)

    def test_history_replays_exact_balances_and_division_mode_can_change(self):
        report, log = prepare_distribution(
            [request(items=[DistributionItem("Кровь", 5)])], ["Кровь"], empty_distribution_log(), seed=11,
        )
        next_report, log = prepare_distribution(
            [request(2, items=[DistributionItem("Кровь", 50)])], [], log, seed=1,
        )
        ledger = distribution_balances(log)["поле боя"]
        for name, value in next_report["events"][0]["balance_after"].items():
            self.assertEqual(ledger["overall"][name.casefold()], Fraction(value))
        self.assertEqual(sum(ledger["overall"].values()), 0)
        self.assertEqual(sum(ledger["items"]["кровь"].values()), 0)

    def test_large_divisible_stack_is_conserved(self):
        report, _ = prepare_distribution(
            [request(items=[DistributionItem("Кровь", 10**9)])], ["Кровь"], empty_distribution_log(), seed=1,
        )
        counts = [row["quantity"] for row in report["events"][0]["items"][0]["allocations"]]
        self.assertEqual(sum(counts), 10**9)
        self.assertEqual(counts, [333_333_334, 333_333_334, 333_333_332])


class MassDistributionPersistenceTests(unittest.TestCase):
    def test_exact_snapshot_survives_restart_without_history_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mass_distribution_log.json"
            store = MassDistributionStore(path)
            store.distribute([request()], [])
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("1/3", raw["balance_cache"]["ledger"]["поле боя"]["overall"].values())
            expected = distribution_balances(raw)
            with patch("syndicate.mass_distribution.distribution_balances", side_effect=AssertionError("unnecessary replay")):
                restarted = MassDistributionStore(path)
                restarted.load()
                self.assertEqual(restarted.balances, expected)
                restarted.distribute([request(2)], [])
                restarted.load()
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(restarted.balances, distribution_balances(updated))

    def test_legacy_history_is_replayed_once_and_migrated_on_next_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mass_distribution_log.json"
            _, legacy = prepare_distribution([request()], [], empty_distribution_log(), seed=3)
            legacy.pop("balance_cache")
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            with patch("syndicate.mass_distribution.distribution_balances", wraps=distribution_balances) as replay:
                store = MassDistributionStore(path)
                store.distribute([request(2)], [])
                self.assertEqual(replay.call_count, 1)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("balance_cache", raw)
            self.assertEqual(raw["reports"][0], legacy["reports"][0])
            self.assertEqual(store.balances, distribution_balances(raw))

    def test_corrupt_cache_is_repaired_but_corrupt_history_still_blocks_saving(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mass_distribution_log.json"
            store = MassDistributionStore(path)
            store.distribute([request()], [])
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["balance_cache"]["ledger"]["поле боя"]["overall"]["а"] = "99"
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            store.distribute([request(2)], [])
            repaired = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(load_distribution_balances(repaired), distribution_balances(repaired))
            repaired["reports"][0]["events"][0]["items"][0]["allocations"][0]["quantity"] = 999
            path.write_text(json.dumps(repaired, ensure_ascii=False), encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "повреждена"):
                store.distribute([request(3)], [])
            self.assertEqual(path.read_bytes(), original)

    def test_history_survives_restart_and_duplicates_are_not_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mass_distribution_log.json"
            first = MassDistributionStore(path).distribute([request()], [])
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "уже распределено"):
                MassDistributionStore(path).distribute([request()], [])
            self.assertEqual(path.read_bytes(), original)
            next_report = MassDistributionStore(path).distribute([request(2)], [])
            self.assertNotEqual(
                first["events"][0]["items"][0]["allocations"][0]["participant"],
                next_report["events"][0]["items"][0]["allocations"][0]["participant"],
            )
            self.assertEqual(len(MassDistributionStore(path).load()["reports"]), 2)

    def test_invalid_batch_and_corrupt_history_are_not_partially_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mass_distribution_log.json"
            store = MassDistributionStore(path)
            with self.assertRaisesRegex(ValueError, "выбрать участников"):
                store.distribute([request(), request(2, names=())], [])
            self.assertFalse(path.exists())
            path.write_text('{"version":1,"reports":[{}]}', encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "повреждена"):
                store.distribute([request()], [])
            self.assertEqual(path.read_bytes(), original)

    def test_write_failure_does_not_confirm_or_change_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mass_distribution_log.json"
            store = MassDistributionStore(path)
            store.distribute([request()], [])
            original = path.read_bytes()
            original_balances = deepcopy(store.balances)
            with patch.object(Path, "replace", side_effect=OSError("нет доступа")):
                with self.assertRaises(OSError):
                    store.distribute([request(2)], [])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(store.balances, original_balances)

    def test_divisible_settings_are_normalized_and_preserved_by_regular_saves(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            store = ParticipantStore(path)
            store.save([Participant("А", bm=100)], divisible_items=[" Кровь ", "кРОВЬ", "Камни"])
            new_store = ParticipantStore(path)
            participants = new_store.load()
            self.assertEqual(new_store.divisible_items, ["Камни", "Кровь"])
            new_store.save(participants, 25)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["mass_distribution"]["divisible_items"], ["Камни", "Кровь"])


if __name__ == "__main__":
    unittest.main()
