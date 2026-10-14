"""Application shell: root window, responsive layout, and subsystem wiring."""
from __future__ import annotations

import math
import os
import queue
import tkinter as tk
from fractions import Fraction
from tkinter import ttk

import numpy as np
from PIL import Image

from .draw_workflow import DrawWorkflowMixin
from .mass_distribution_ui import MassDistributionPanel
from .mass_distribution import DistributionRequest, distribution_statistics
from .models import DrawResult, Participant, RecordedWheelFrame, nickname_lookup_key, sort_participants_by_bm
from .participants_ui import ParticipantsPanel
from .platform import (
    apply_dark_title_bar,
    apply_window_icon,
    keep_dark_title_bar,
    monitor_size_for_window,
)
from .storage import DrawLogStore, MassDistributionStore, ParticipantStore
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    APP_NAME,
    BACKGROUND,
    DESIGN_SCREEN_HEIGHT,
    DESIGN_SCREEN_WIDTH,
    MAX_UI_SCALE,
    MIN_UI_SCALE,
    MUTED,
    SURFACE_LIGHT,
    TEXT,
    TEXT_BRIGHT,
    WINNER_BACKGROUND,
)
from .wheel_rendering import WheelRenderingMixin
from .widgets import AnimatedEllipsis, PrizeImageCard, PrizeQuantityControl, WinnerNicknameCopy, primary_action_button, styled_button


class WheelApp(DrawWorkflowMixin, WheelRenderingMixin, tk.Tk):
    LEFT_PANEL_WIDTH = 820
    CANVAS_SIZE = 780
    CANVAS_HEIGHT = 740
    CENTER_X = 390
    CENTER_Y = 376
    RADIUS = 352
    CENTER_MEDALLION_RADIUS = 70
    GUILD_ICON_SIZE = 112
    LABEL_RADIUS_RATIO = 0.67
    DENSE_LABEL_RADIUS_RATIO = 0.74
    ANTIALIAS_SCALE = 4
    DISC_ANTIALIAS_SCALE = 4
    SPIN_DURATION_SECONDS = 4.8
    MULTI_SPIN_DURATION_SECONDS = 3.6
    MULTI_WINNER_HOLD_SECONDS = 0.65
    SECTOR_TRANSITION_SECONDS = 0.70
    VIDEO_FPS = 24
    VIDEO_CAPTURE_HEIGHT = 912
    VIDEO_FINAL_HOLD_SECONDS = 2.0
    PRIZE_UI_MAX_CARD_WIDTH = 465

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.ui_scale = self._calculate_ui_scale()
        self._native_tk_scaling = 1.0
        try:
            self._native_tk_scaling = float(self.tk.call("tk", "scaling"))
            self.tk.call(
                "tk", "scaling", self._native_tk_scaling * self.ui_scale
            )
        except (tk.TclError, TypeError, ValueError):
            pass
        self._update_display_metrics()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.store = ParticipantStore()
        self.draw_log_store = DrawLogStore()
        self.mass_distribution_store = MassDistributionStore()
        try:
            distribution_log = self.mass_distribution_store.load()
            self._distribution_reports = distribution_log["reports"]
            self._distribution_balances = self.mass_distribution_store.balances
        except (OSError, ValueError, TypeError):
            self._distribution_reports = []
            self._distribution_balances = {}
        self._distribution_statistics = distribution_statistics(self._distribution_reports)
        try:
            self.draw_log_store.migrate()
        except (OSError, ValueError, TypeError):
            # A damaged or read-only history must not prevent the app opening.
            pass
        self.participants = sort_participants_by_bm(self.store.load())
        self.bm_influence_percent = self.store.bm_influence_percent
        self.nickname_corrections = list(self.store.nickname_corrections)
        self.penalty_settings = self.store.penalty_settings
        self.rotation = 0.0
        self.spinning = False
        self._winner_index: int | None = None
        self._show_winner_glow = False
        self._roll_slots: list[Participant] | None = None
        self._roll_remaining: list[Participant] = []
        self._roll_probabilities: list[float] | None = None
        self._roll_penalty_statuses = {}
        self._roll_penalty_coefficients: dict[str, float] = {}
        self._roll_apply_penalty = True
        self._roll_winners: list[str] = []
        self._roll_target_count = 1
        self._wheel_cache_key: tuple[float, ...] | None = None
        self._wheel_render_queue: queue.Queue[
            tuple[int, tuple[float, ...], Image.Image | None]
        ] = queue.Queue()
        self._wheel_render_generation = 0
        self._wheel_render_jobs = 0
        self._wheel_render_polling = False
        self._wheel_pending_key: tuple[float, ...] | None = None
        self._wheel_disc_array: np.ndarray | None = None
        self._video_frames: list[RecordedWheelFrame] = []
        self._video_generation = 0
        self._video_queue: queue.Queue[tuple[int, bytes | Exception]] = queue.Queue()
        self._video_polling = False
        self._video_jobs = 0
        self._roll_video_bytes: bytes | None = None
        self._roll_prize_image: Image.Image | None = None
        self._roll_prize_quantity = 1
        self._video_preparation_failed = False
        self._reward_ocr_generation = 0
        self._reward_ocr_queue: queue.Queue[tuple[int, str | Exception]] = (
            queue.Queue()
        )
        self._reward_ocr_jobs = 0
        self._reward_ocr_polling = False
        self._reward_ocr_pending = False
        self._pending_draw_results: list[DrawResult] = []
        self._roll_logged = False
        self._monitor_check_after_id: str | None = None
        self._show_main_after_id: str | None = None
        self._finish_show_after_id: str | None = None
        self._rebuilding_ui = False
        self._active_mode = "draw"
        self.button_process_text = AnimatedEllipsis(self)

        self.title(APP_NAME)
        apply_window_icon(self, default=True)
        self.geometry(f"{self._px(1280)}x{self._px(760)}")
        self.minsize(self._px(1050), self._px(650))
        self.resizable(True, True)
        self.configure(bg=BACKGROUND)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        keep_dark_title_bar(self)

        self._configure_styles()
        self._build_ui()
        self._draw_wheel()
        self.bind("<Configure>", self._on_window_configure, add="+")
        self._show_main_after_id = self.after_idle(self._show_main_window)

    def destroy(self) -> None:
        for attribute in (
            "_monitor_check_after_id",
            "_show_main_after_id",
            "_finish_show_after_id",
        ):
            callback_id = getattr(self, attribute, None)
            if callback_id is None:
                continue
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)
        super().destroy()

    def _calculate_ui_scale(self) -> float:
        width, height = monitor_size_for_window(self)
        return self._scale_for_monitor(width, height)

    @staticmethod
    def _scale_for_monitor(width: int, height: int) -> float:
        width_ratio = width / DESIGN_SCREEN_WIDTH
        height_ratio = height / DESIGN_SCREEN_HEIGHT
        return min(MAX_UI_SCALE, max(MIN_UI_SCALE, min(width_ratio, height_ratio)))

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _update_display_metrics(self) -> None:
        self.display_left_panel_width = self._px(self.LEFT_PANEL_WIDTH)
        self.display_canvas_size = self._px(self.CANVAS_SIZE)
        self.display_canvas_height = self._px(self.CANVAS_HEIGHT)

    def _on_window_configure(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self or self._rebuilding_ui:
            return
        if self._monitor_check_after_id is not None:
            try:
                self.after_cancel(self._monitor_check_after_id)
            except tk.TclError:
                pass
        self._monitor_check_after_id = self.after(180, self._check_monitor_scale)

    def _check_monitor_scale(self) -> None:
        self._monitor_check_after_id = None
        if not self.winfo_exists():
            return
        width, height = monitor_size_for_window(self)
        new_scale = self._scale_for_monitor(width, height)
        if math.isclose(new_scale, self.ui_scale, abs_tol=0.005):
            return

        import_open = (
            hasattr(self, "participants_panel")
            and self.participants_panel.import_dialog is not None
            and self.participants_panel.import_dialog.winfo_exists()
        )
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        editing = (
            isinstance(focused, tk.Entry)
            and hasattr(self, "participants_panel")
            and self.participants_panel._is_panel_widget(focused)
        )
        if self.spinning or self._video_jobs or import_open or editing:
            self._monitor_check_after_id = self.after(
                250, self._check_monitor_scale
            )
            return
        self._rebuild_scaled_ui(new_scale)

    def _rebuild_scaled_ui(self, new_scale: float) -> None:
        if self._rebuilding_ui:
            return
        self._rebuilding_ui = True
        try:
            self.participants_panel.flush_auto_save()
            self.participants_panel._store_distribution_selection()
            distribution_snapshot = self.mass_distribution_panel.snapshot()
            participant_selections = {
                nickname_lookup_key(row["name"].get()): dict(row.get("distribution_enabled", {}))
                for row in self.participants_panel.rows
            }
            prize_image = (
                self.prize_card.image.copy()
                if self.prize_card.image is not None
                else None
            )
            prize_locked = self.prize_card.locked
            prize_quantity = self.prize_quantity_control.value()
            prize_quantity_locked = self.prize_quantity_control.locked
            result_text = self.result_var.get()
            result_visible = bool(self.result_actions.winfo_manager())
            save_button_options = {
                option: self.save_result_button.cget(option)
                for option in (
                    "text",
                    "state",
                    "bg",
                    "highlightbackground",
                    "highlightcolor",
                )
            }

            self.button_process_text.stop()
            self.content.destroy()
            if hasattr(self, "_wheel_image"):
                del self._wheel_image

            self.ui_scale = new_scale
            try:
                self.tk.call(
                    "tk",
                    "scaling",
                    self._native_tk_scaling * self.ui_scale,
                )
            except tk.TclError:
                pass
            self._update_display_metrics()
            self.geometry(f"{self._px(1280)}x{self._px(760)}")
            self.minsize(self._px(1050), self._px(650))
            self._configure_styles()
            self._build_ui()
            for row in self.participants_panel.rows:
                row["distribution_enabled"] = participant_selections.get(nickname_lookup_key(row["name"].get()), {})
            self.mass_distribution_panel.restore_snapshot(distribution_snapshot)

            if prize_image is not None:
                self.prize_card.set_image(prize_image)
            self.prize_card.set_locked(prize_locked)
            self.prize_quantity_control.set_value(prize_quantity)
            self.prize_quantity_control.set_locked(prize_quantity_locked)
            if result_text:
                self._show_winner_result(result_text)
                if result_visible:
                    self._show_result_controls()
                    self.save_result_button.configure(**save_button_options)
            else:
                self._clear_winner_result()
                self._show_spin_controls()
            self._draw_wheel()
            self._maximize_window()
            self.after_idle(self.participants_panel._update_scrollbar_visibility)
            apply_dark_title_bar(self)
        finally:
            self._rebuilding_ui = False

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Vertical.TScrollbar",
            background="#414741",
            troughcolor="#151815",
            bordercolor="#151815",
            lightcolor="#414741",
            darkcolor="#414741",
            arrowcolor=MUTED,
            relief="flat",
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#59615A")],
            lightcolor=[("active", "#59615A")],
            darkcolor=[("active", "#59615A")],
        )

    def _build_ui(self) -> None:
        content = tk.Frame(self, bg=BACKGROUND)
        self.content = content
        content.pack(fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        left_host = tk.Frame(
            content,
            bg=BACKGROUND,
            width=self.display_left_panel_width,
            highlightthickness=1,
            highlightbackground="#383E39",
        )
        self.left_host = left_host
        left_host.grid(row=0, column=0, sticky="ns")
        left_host.grid_propagate(False)
        left_host.grid_rowconfigure(0, weight=1)
        left_host.grid_columnconfigure(0, weight=1)

        left_panel = tk.Frame(left_host, bg=BACKGROUND)
        self.draw_panel = left_panel
        left_panel.grid(row=0, column=0, sticky="nsew")

        header = tk.Frame(left_panel, bg=BACKGROUND, height=self._px(78))
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(18), 0),
        )
        header.pack_propagate(False)

        title_block = tk.Frame(header, bg=BACKGROUND)
        title_block.pack(side="left", anchor="w")
        tk.Label(
            title_block,
            text=APP_NAME,
            bg=BACKGROUND,
            fg="#D9DDD9",
            font=("Segoe UI Semibold", 21),
        ).pack(anchor="w")
        self.count_label = tk.Label(
            title_block,
            bg=BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.count_label.pack(anchor="w", pady=(self._px(2), 0))

        prize_group = tk.Frame(header, bg=BACKGROUND)
        prize_group.pack(side="right", anchor="center")
        self.prize_card = PrizeImageCard(
            prize_group,
            max_card_width=self.PRIZE_UI_MAX_CARD_WIDTH,
            on_clear=lambda: self.prize_quantity_control.set_value(1),
        )
        self.prize_card.grid(row=0, column=0)
        self.prize_quantity_control = PrizeQuantityControl(prize_group)
        self.prize_quantity_control.grid(
            row=0,
            column=1,
            padx=(self._px(4), 0),
        )

        self.wheel_canvas = tk.Canvas(
            left_panel,
            width=self.display_canvas_size,
            height=self.display_canvas_height,
            bg=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.wheel_canvas.pack()

        controls = tk.Frame(left_panel, bg=BACKGROUND)
        controls.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(2), self._px(18)),
        )

        self.result_var = tk.StringVar(value="")
        self.result_slot = tk.Frame(
            controls,
            bg=BACKGROUND,
            height=self._px(64),
        )
        self.result_slot.pack(fill="x", pady=(0, self._px(8)))
        self.result_slot.pack_propagate(False)

        self.result_card = tk.Frame(
            self.result_slot,
            bg=WINNER_BACKGROUND,
            highlightthickness=1,
            highlightbackground=ACCENT,
        )
        self.result_caption = tk.Label(
            self.result_card,
            text="ПОБЕДИТЕЛЬ",
            bg=WINNER_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        )
        self.result_caption.pack(pady=(self._px(5), self._px(1)))
        self.result_divider = tk.Frame(
            self.result_card,
            bg=ACCENT,
            height=self._px(1),
        )
        self.result_divider.pack(fill="x", padx=self._px(260))
        self.result_label = tk.Label(
            self.result_card,
            textvariable=self.result_var,
            bg=WINNER_BACKGROUND,
            fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 18),
            anchor="center",
        )
        self.result_label.pack(
            fill="x", pady=(self._px(1), self._px(4))
        )
        self.winner_nickname_copy = WinnerNicknameCopy(self.result_label, self.result_caption)

        self.result_sort_button = tk.Button(
            self.result_card,
            text="⇅",
            command=self._sort_winner_result_by_bm,
            bg=WINNER_BACKGROUND,
            fg=MUTED,
            activebackground=SURFACE_LIGHT,
            activeforeground=ACCENT_HOVER,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            cursor="hand2",
            takefocus=False,
            font=("Segoe UI Symbol", 13),
            padx=0,
            pady=0,
        )

        def sort_enter(_event: tk.Event[tk.Misc]) -> None:
            self.result_sort_button.configure(
                bg=SURFACE_LIGHT,
                fg=ACCENT_HOVER,
            )

        def sort_leave(_event: tk.Event[tk.Misc]) -> None:
            self.result_sort_button.configure(
                bg=WINNER_BACKGROUND,
                fg=MUTED,
            )

        self.result_sort_button.bind("<Enter>", sort_enter)
        self.result_sort_button.bind("<Leave>", sort_leave)

        self.action_slot = tk.Frame(controls, bg=BACKGROUND)
        self.action_slot.pack(fill="x")

        self.spin_button = primary_action_button(self.action_slot, "КРУТИТЬ КОЛЕСО", self._start_spin)
        self.spin_button.pack(fill="x")

        self.result_actions = tk.Frame(self.action_slot, bg=BACKGROUND)
        self.result_actions.grid_columnconfigure(0, weight=1, uniform="roll_actions")
        self.result_actions.grid_columnconfigure(1, weight=1, uniform="roll_actions")
        self.save_result_button = styled_button(
            self.result_actions,
            "СОХРАНИТЬ РЕЗУЛЬТАТ",
            self._save_roll_video,
            ACCENT,
            "#F1EEE5",
        )
        self.save_result_button.configure(
            font=("Segoe UI Semibold", 11),
            pady=self._px(11),
        )
        self.save_result_button.grid(
            row=0, column=0, sticky="ew", padx=(0, self._px(5))
        )
        self.cancel_result_button = styled_button(
            self.result_actions,
            "ОТМЕНА",
            self._cancel_roll_result,
            SURFACE_LIGHT,
            TEXT,
        )
        self.cancel_result_button.configure(
            font=("Segoe UI Semibold", 11),
            pady=self._px(11),
        )
        self.cancel_result_button.grid(
            row=0, column=1, sticky="ew", padx=(self._px(5), 0)
        )

        self.mass_distribution_panel = MassDistributionPanel(
            left_host,
            ui_scale=self.ui_scale,
            on_event_selected=self._select_distribution_event,
            on_paste_participants=self._paste_distribution_participants,
            on_distribute=self._distribute_mass_rewards,
            on_divisible_items_changed=self._save_divisible_items,
            on_raffle_items_changed=self._save_raffle_items,
            on_load_reports=self._load_distribution_reports,
            divisible_items=self.store.divisible_items,
            raffle_items=self.store.raffle_items,
        )
        self.mass_distribution_panel.grid(row=0, column=0, sticky="nsew")

        self.participants_panel = ParticipantsPanel(content, self)
        self.participants_panel.grid(row=0, column=1, sticky="nsew")
        self._show_active_mode()
        self._update_count()

    def _select_distribution_event(
        self,
        event_key: tuple[str, str] | None,
    ) -> None:
        self.participants_panel.select_distribution_event(event_key)

    def update_distribution_event_participants(
        self,
        event_key: tuple[str, str],
        participant_names: list[str],
    ) -> None:
        self.mass_distribution_panel.set_event_participants(
            event_key,
            participant_names,
        )

    def _paste_distribution_participants(
        self,
        event_key: tuple[str, str],
        clipboard_text: str,
    ) -> list[str]:
        return self.participants_panel.apply_distribution_participants_text(
            event_key,
            clipboard_text,
        )

    def _show_active_mode(self) -> None:
        if self._active_mode == "mass_distribution":
            self.mass_distribution_panel.tkraise()
        else:
            self.draw_panel.tkraise()
        self.participants_panel.set_mass_distribution_mode(
            self._active_mode == "mass_distribution"
        )
        if self._active_mode == "draw" and getattr(self, "_wheel_redraw_deferred", False):
            self._request_wheel_redraw()

    def _save_divisible_items(self, names: list[str]) -> None:
        self.participants_panel.flush_auto_save()
        self.store.save(self.participants, divisible_items=names)

    def _save_raffle_items(self, names: list[str]) -> None:
        self.participants_panel.flush_auto_save()
        self.store.save(self.participants, raffle_items=names)

    def _load_distribution_reports(self) -> list[dict]:
        return self.mass_distribution_store.load()["reports"]

    def _distribute_mass_rewards(self, requests: list[DistributionRequest]) -> dict:
        requests = [
            DistributionRequest(
                request.event,
                tuple(self.participants_panel.distribution_participant_names(request.event.key)),
            )
            for request in requests
        ]
        report = self.mass_distribution_store.distribute(requests, self.store.divisible_items)
        self._distribution_balances = self.mass_distribution_store.balances
        self._distribution_reports.append(report)
        self._distribution_statistics = distribution_statistics(self._distribution_reports)
        for row in self.participants_panel.rows:
            self.participants_panel._update_row_last_win(row)
        return report

    def distribution_balance_for(self, event_name: str, participant_name: str) -> Fraction:
        ledger = self._distribution_balances.get(nickname_lookup_key(event_name), {})
        return ledger.get("overall", {}).get(nickname_lookup_key(participant_name), Fraction())

    def distribution_statistics_for(self, event_name: str | None, participant_name: str) -> tuple[int, int]:
        key = nickname_lookup_key(participant_name)
        if event_name is None:
            totals = [statistics.get(key, (0, 0)) for statistics in self._distribution_statistics.values()]
            return sum(value[0] for value in totals), sum(value[1] for value in totals)
        statistics = self._distribution_statistics.get(nickname_lookup_key(event_name), {})
        return statistics.get(key, (0, 0))

    def show_mass_distribution(self) -> None:
        """Replace the wheel with the mass-distribution workspace."""

        if self.spinning:
            return
        self.participants_panel.flush_auto_save()
        self.focus_set()
        self._active_mode = "mass_distribution"
        self._show_active_mode()

    def show_draw_mode(self) -> None:
        """Restore the wheel without resetting its state."""

        self.focus_set()
        self._active_mode = "draw"
        self._show_active_mode()

    def _show_main_window(self) -> None:
        """Reveal the app only after its native frame has its final styling."""

        self._show_main_after_id = None
        self.update_idletasks()
        apply_dark_title_bar(self)
        self._maximize_window()
        apply_dark_title_bar(self)
        self.deiconify()
        self._finish_show_after_id = self.after(
            10,
            self._finish_show_main_window,
        )

    def _finish_show_main_window(self) -> None:
        self._finish_show_after_id = None
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass


def configure_windows_process() -> None:
    if os.name != "nt":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        from ctypes import windll

        windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SYNDICATE.DesktopApp"
        )
    except (AttributeError, OSError):
        pass
