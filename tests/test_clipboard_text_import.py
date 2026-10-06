import unittest

from syndicate.import_ui import parse_clipboard_participants


class ClipboardTextImportTests(unittest.TestCase):
    def test_extracts_nicknames_and_bm_from_guild_table_rows(self) -> None:
        text = (
            "Мастер\tРунная воительница\tAsper\t69\t262\u00a0471\tВ сети\n"
            "Старейшина\tЛучница\tPjanka\t70\t320 794\tВ сети\n"
            "Участник\tСкальд\tネリエル\t67\t228\u202f377\tВ сети"
        )

        participants = parse_clipboard_participants(text)

        self.assertEqual(
            [(participant.name, participant.bm) for participant in participants],
            [("Asper", 262471), ("Pjanka", 320794), ("ネリエル", 228377)],
        )
        self.assertTrue(all(participant.confidence == 100 for participant in participants))

    def test_skips_rows_that_do_not_match_the_table_format(self) -> None:
        text = "Заголовок\tИгрок\tБМ\nРоль\tКласс\tPlayer\t70\tне число\tВ сети"

        self.assertEqual(parse_clipboard_participants(text), [])


if __name__ == "__main__":
    unittest.main()
