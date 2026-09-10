import json
import tempfile
import unittest
from pathlib import Path

from syndicate.storage import ParticipantStore
from syndicate.theme import DEFAULT_BM_INFLUENCE_PERCENT


class ParticipantStoreTests(unittest.TestCase):
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

    def test_invalid_data_file_does_not_restore_demo_participants(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            path.write_text("not valid json", encoding="utf-8")

            participants = ParticipantStore(path).load()

            self.assertEqual(participants, [])


if __name__ == "__main__":
    unittest.main()
