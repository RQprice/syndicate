import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from syndicate.application import WheelApp
from syndicate.models import (
    NicknameCorrection,
    Participant,
)
from syndicate.storage import ParticipantStore


class NicknameCorrectionTests(unittest.TestCase):
    def make_app_state(self, path: Path) -> SimpleNamespace:
        return SimpleNamespace(
            participants=[Participant("Existing", False, 100.0)],
            bm_influence_percent=30.0,
            nickname_corrections=[],
            store=ParticipantStore(path),
        )

    def test_correction_is_saved_and_applied_to_normalized_ocr_name(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            app = self.make_app_state(path)

            WheelApp.remember_nickname_corrections(app, [("лена", "леnа")])

            self.assertEqual(
                WheelApp.corrected_nickname(app, "  ЛЕНА "),
                "леnа",
            )
            reloaded = ParticipantStore(path)
            reloaded.load()
            self.assertEqual(
                reloaded.nickname_corrections,
                [NicknameCorrection("лена", "леnа")],
            )

    def test_correction_can_be_updated_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            app = self.make_app_state(path)
            WheelApp.remember_nickname_corrections(app, [("лена", "леnа")])

            WheelApp.remember_nickname_corrections(app, [("ЛЕНА", "леNа")])
            self.assertEqual(len(app.nickname_corrections), 1)
            self.assertEqual(
                WheelApp.corrected_nickname(app, "лена"),
                "леNа",
            )

            WheelApp.remove_nickname_correction(app, "лена")
            self.assertEqual(app.nickname_corrections, [])
            self.assertEqual(WheelApp.corrected_nickname(app, "лена"), "лена")


if __name__ == "__main__":
    unittest.main()
