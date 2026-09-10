"""Compatibility entry point for the modular SYNDICATE application.

Implementation lives in the :mod:`syndicate` package. Existing imports from
``app`` remain supported for tests and external launch scripts.
"""
from __future__ import annotations

from tkinter import messagebox

from ocr_import import (
    OcrError,
    RecognizedParticipant,
    clipboard_image,
    recognize_participants,
    recognize_reward_name,
)
from syndicate.application import WheelApp, configure_windows_process
from syndicate.history_ui import DateRangePicker, DrawHistoryDialog
from syndicate.import_ui import NicknameCorrectionsDialog, ScreenshotImportDialog
from syndicate.models import (
    DrawResult,
    LastWinInfo,
    NicknameCorrection,
    Participant,
    RecordedWheelFrame,
    clean_nickname,
    draw_result_date,
    format_bm,
    format_draw_timestamp,
    format_draws_ago,
    last_win_statistics,
    nickname_lookup_key,
    parse_bm,
    sort_participants_by_bm,
)
from syndicate.participants_ui import ParticipantsPanel
from syndicate.platform import (
    application_directory,
    apply_dark_title_bar,
    apply_window_icon,
    clipboard_sequence_number,
    enable_entry_shortcuts,
    handle_entry_shortcut,
    is_foreground_window,
    keep_dark_title_bar,
    monitor_size_for_window,
    resource_path,
    scaled_px,
    widget_ui_scale,
)
from syndicate.probabilities import (
    participant_probabilities,
    participant_weights,
    weighted_random_index,
)
from syndicate.storage import DrawLogStore, ParticipantStore
from syndicate.theme import *  # noqa: F403 - compatibility re-export
from syndicate.video import encode_mp4_frames
from syndicate.widgets import (
    AnimatedEllipsis,
    PrizeImageCard,
    PrizeQuantityControl,
    StyledCheckbutton,
    StyledDeleteButton,
    styled_button,
)


def main() -> None:
    configure_windows_process()
    application = WheelApp()
    application.mainloop()


if __name__ == "__main__":
    main()
