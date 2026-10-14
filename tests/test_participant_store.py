import json
import tempfile
import unittest
from pathlib import Path

from syndicate.models import Participant, PenaltySettings
from syndicate.storage import ParticipantStore
from syndicate.theme import DEFAULT_BM_INFLUENCE_PERCENT


class ParticipantStoreTests(unittest.TestCase):
    def test_item_categories_are_saved_independently_and_survive_regular_saves(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            store = ParticipantStore(path)
            store.save([], divisible_items=["Кровь Имира"])
            store.save([], raffle_items=[" Верх Кари ", "верх кари"])
            store.save([Participant("Игрок", bm=100)], 50)

            reloaded = ParticipantStore(path)
            reloaded.load()
            self.assertEqual(reloaded.divisible_items, ["Кровь Имира"])
            self.assertEqual(reloaded.raffle_items, ["Верх Кари"])
            reloaded.save([], divisible_items=[])
            final = ParticipantStore(path)
            final.load()
            self.assertEqual(final.divisible_items, [])
            self.assertEqual(final.raffle_items, ["Верх Кари"])

    def test_missing_data_file_is_created_without_demo_participants(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"

            participants = ParticipantStore(path).load()

            self.assertEqual(participants, [])
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["participants"], [])
            self.assertEqual(payload["nickname_corrections"], [])
            self.assertEqual(
                payload["bm_influence_percent"],
                DEFAULT_BM_INFLUENCE_PERCENT,
            )
            self.assertEqual(
                payload["winner_penalty"],
                {
                    "enabled": True,
                    "recovery_participations": 4,
                    "chance_steps": [0.25, 0.4, 0.6, 0.8, 1.0],
                },
            )

    def test_invalid_data_file_does_not_restore_demo_participants(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            path.write_text("not valid json", encoding="utf-8")

            participants = ParticipantStore(path).load()

            self.assertEqual(participants, [])

    def test_penalty_settings_are_saved_loaded_and_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            store = ParticipantStore(path)
            settings = PenaltySettings(
                enabled=False,
                chance_steps=(0.2, 0.5, 0.75, 1.0),
            )

            store.save([Participant("Player", bm=123.0)], penalty_settings=settings)

            reloaded = ParticipantStore(path)
            self.assertEqual(
                reloaded.load(),
                [Participant("Player", False, 123.0)],
            )
            self.assertEqual(reloaded.penalty_settings, settings)

            reloaded.save([Participant("Player", bm=456.0)], 30.0)
            loaded_again = ParticipantStore(path)
            loaded_again.load()
            self.assertEqual(loaded_again.penalty_settings, settings)

    def test_old_data_file_uses_default_penalty_settings(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            path.write_text(
                json.dumps(
                    {
                        "bm_influence_percent": 50,
                        "participants": [],
                        "nickname_corrections": [],
                    }
                ),
                encoding="utf-8",
            )
            store = ParticipantStore(path)

            store.load()

            self.assertEqual(store.penalty_settings, PenaltySettings())

    def test_penalty_scale_has_no_fixed_length_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            steps = tuple(index / 20 for index in range(1, 21))
            settings = PenaltySettings(chance_steps=steps)
            store = ParticipantStore(path)

            store.save([], penalty_settings=settings)
            reloaded = ParticipantStore(path)
            reloaded.load()

            self.assertEqual(reloaded.penalty_settings, settings)


if __name__ == "__main__":
    unittest.main()
