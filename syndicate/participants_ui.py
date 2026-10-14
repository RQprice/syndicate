"""Editable two-column guild participant list and its controls."""
from __future__ import annotations

import math
import re
import tkinter as tk
from tkinter import messagebox, ttk

from .history_ui import DrawHistoryDialog
from .import_ui import ScreenshotImportDialog
from .models import (
    DrawResult,
    LastWinInfo,
    Participant,
    PenaltySettings,
    clean_nickname,
    format_bm,
    format_draw_timestamp,
    format_draws_ago,
    last_win_statistics,
    nickname_lookup_key,
    parse_bm,
    sort_participants_by_bm,
)
from .penalties import (
    WinnerPenaltyStatus,
    format_penalty_coefficient,
    format_remaining_draws,
    winner_penalty_statuses,
)
from .penalty_ui import PenaltySettingsDialog
from .platform import enable_entry_shortcuts, scaled_px, widget_ui_scale
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    APP_NAME,
    BORDER,
    BORDER_LIGHT,
    BUTTON_BORDER,
    BUTTON_HOVER,
    BUTTON_HOVER_BORDER,
    DANGER,
    DISABLED_TEXT,
    INPUT_BACKGROUND,
    MUTED,
    PANEL_BACKGROUND,
    ROW_HOVER,
    ROW_SELECTED,
    ROW_SELECTED_HOVER,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
)
from .widgets import StyledCheckbutton, StyledDeleteButton, styled_button


class ParticipantsPanel(tk.Frame):
    SELECTION_UPDATE_DELAY_MS = 90

    def __init__(self, parent: tk.Misc, owner: "WheelApp") -> None:
        super().__init__(parent, bg=PANEL_BACKGROUND)
        self.owner = owner
        self.ui_scale = float(getattr(owner, "ui_scale", widget_ui_scale(parent)))
        self.rows: list[dict[str, object]] = []
        self.import_dialog: ScreenshotImportDialog | None = None
        self.history_dialog: DrawHistoryDialog | None = None
        self.penalty_dialog: PenaltySettingsDialog | None = None
        self.penalty_settings = owner.penalty_settings
        self._auto_save_ready = False
        self._auto_save_after_id: str | None = None
        self._save_pending = False
        self._last_save_error = ""
        self._focus_move_after_id: str | None = None
        self._scroll_update_after_id: str | None = None
        self._scroll_region = None
        self._rows_canvas_width: int | None = None
        self._syncing_select_all = False
        self._bulk_selection = False
        self._clear_focus_after_restore = False
        self._last_win_statistics: dict[str, LastWinInfo] = {}
        self._last_win_results: dict[str, DrawResult] = {}
        self._penalty_statuses: dict[str, WinnerPenaltyStatus] = {}
        self._mass_distribution_mode = False
        self._active_distribution_event_key: tuple[str, str] | None = None
        self._distribution_pulse_after_id: str | None = None
        self._distribution_pulse_step = 0
        self._last_win_tooltip: tk.Toplevel | None = None
        self._last_win_tooltip_anchor: tk.Widget | None = None
        self._last_win_tooltip_hide_job: str | None = None
        self._load_last_win_statistics()
        influence = owner.bm_influence_percent
        influence_text = (
            str(int(influence))
            if float(influence).is_integer()
            else f"{influence:.2f}".rstrip("0").rstrip(".")
        )
        self.influence_var = tk.StringVar(value=influence_text)

        self._build_ui()
        for participant in sort_participants_by_bm(owner.participants):
            self._add_row(
                participant.name,
                participant.enabled,
                participant.bm,
                scroll_to_end=False,
            )
        self.influence_var.trace_add("write", self._on_text_value_changed)
        self.influence_entry.bind("<FocusIn>", self._on_entry_focus_in, add="+")
        self.influence_entry.bind("<FocusOut>", self._on_entry_focus_out, add="+")
        self._click_binding_id = self.owner.bind_all(
            "<Button-1>", self._clear_entry_focus_on_click, add="+"
        )
        self._return_binding_id = self.owner.bind_all(
            "<Return>", self._clear_entry_focus_on_enter, add="+"
        )
        self._unmap_binding_id = self.owner.bind(
            "<Unmap>", self._on_owner_unmap, add="+"
        )
        self._map_binding_id = self.owner.bind(
            "<Map>", self._on_owner_map, add="+"
        )
        self._auto_save_ready = True
        self.after_idle(lambda: self.canvas.yview_moveto(0.0))

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _load_last_win_statistics(self) -> None:
        try:
            results = self.owner.draw_log_store.load()
        except (OSError, ValueError, TypeError):
            results = []
        self._last_win_statistics = last_win_statistics(results)
        self._penalty_statuses = winner_penalty_statuses(
            results,
            self.penalty_settings,
        )
        self._last_win_results = {}
        for result in reversed(results):
            key = clean_nickname(result.winner)
            if key and key not in self._last_win_results:
                self._last_win_results[key] = result

    def refresh_last_wins(self) -> None:
        self._hide_last_win_tooltip()
        self._load_last_win_statistics()
        for row_data in self.rows:
            self._update_row_last_win(row_data)

    def active_penalty_coefficients(self) -> dict[str, float]:
        return {
            name: status.coefficient
            for name, status in self._penalty_statuses.items()
        }

    def active_penalty_statuses(self) -> dict[str, WinnerPenaltyStatus]:
        return dict(self._penalty_statuses)

    def selected_penalty_coefficients(self) -> dict[str, float]:
        if not self.apply_penalty_var.get():
            return {}
        return self.active_penalty_coefficients()

    def _toggle_apply_penalty(self, _event: tk.Event[tk.Misc]) -> str:
        if str(self.apply_penalty_check.cget("state")) != "disabled":
            self.apply_penalty_var.set(not self.apply_penalty_var.get())
        return "break"

    def _on_apply_penalty_changed(self, *_args: object) -> None:
        if not self.owner.spinning:
            self.owner._request_wheel_redraw()

    def _build_ui(self) -> None:
        heading = tk.Frame(
            self,
            bg=PANEL_BACKGROUND,
            height=self._px(41),
        )
        heading.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(18), self._px(10)),
        )
        heading.pack_propagate(False)

        tk.Label(
            heading,
            text="УЧАСТНИКИ",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left", anchor="w")
        self.guild_count_label = tk.Label(
            heading,
            text="· 0",
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 14),
        )
        self.guild_count_label.pack(
            side="left", padx=(self._px(7), 0), pady=(self._px(2), 0)
        )
        self.mass_distribution_button = styled_button(
            heading,
            "Массовое распределение",
            self.owner.show_mass_distribution,
            SURFACE_LIGHT,
            TEXT,
        )
        self.mass_distribution_button.pack(
            side="left",
            padx=(self._px(16), 0),
        )

        self.import_button = styled_button(
            heading, "Из буфера", self._open_import, SURFACE_LIGHT, TEXT
        )
        self.import_button.pack(side="right")
        self.add_button = styled_button(
            heading, "+  Добавить", self._add_empty_row, SURFACE_LIGHT, TEXT
        )
        self.add_button.pack(side="right", padx=(0, self._px(8)))
        self.history_separator = tk.Frame(
            heading,
            bg=BORDER,
            width=self._px(1),
        )
        self.history_separator.pack(
            side="right",
            fill="y",
            padx=self._px(12),
            pady=self._px(2),
        )
        self.history_button = styled_button(
            heading,
            "История",
            self._open_history,
            SURFACE_LIGHT,
            TEXT,
        )
        self.history_button.pack(side="right")

        self.distribution_header_separator = tk.Frame(
            heading, bg=BORDER, width=self._px(1),
        )
        self.distribution_header_controls = tk.Frame(heading, bg=PANEL_BACKGROUND)
        self.distribution_reports_button = styled_button(
            self.distribution_header_controls, "Отчёты",
            lambda: self.owner.mass_distribution_panel._open_reports(), SURFACE_LIGHT, TEXT,
        )
        self.distribution_reports_button.pack(side="left", padx=(0, self._px(8)))
        self.item_settings_button = styled_button(
            self.distribution_header_controls, "Настройки предметов",
            lambda: self.owner.mass_distribution_panel._open_item_settings(), SURFACE_LIGHT, TEXT,
        )
        self.item_settings_button.pack(side="left")

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.list_shell = list_shell
        list_shell.pack(fill="both", expand=True, padx=self._px(24))

        columns_header = tk.Frame(
            list_shell, bg=SURFACE, height=self._px(27)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        columns_header.grid_columnconfigure(0, weight=1, uniform="headers")
        columns_header.grid_columnconfigure(1, weight=1, uniform="headers")
        self.last_win_header_labels: list[tk.Label] = []
        self.last_win_header_separators: list[tk.Frame] = []
        for column in range(2):
            column_header = tk.Frame(columns_header, bg=SURFACE)
            column_header.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(self._px(6), self._px(3))
                if column == 0
                else (self._px(3), self._px(6)),
            )
            column_header.grid_rowconfigure(0, weight=1)
            column_header.grid_columnconfigure(0, minsize=self._px(60))
            column_header.grid_columnconfigure(1, weight=1)
            column_header.grid_columnconfigure(2, minsize=self._px(89))
            column_header.grid_columnconfigure(3, minsize=self._px(1))
            column_header.grid_columnconfigure(4, minsize=self._px(144))
            column_header.grid_columnconfigure(5, minsize=self._px(48))
            tk.Label(
                column_header,
                text="ИГРОК",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            ).grid(
                row=0,
                column=1,
                sticky="w",
            )
            last_win_heading = tk.Label(
                column_header,
                text="ПОСЛЕДНЯЯ ПОБЕДА",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            )
            last_win_heading.grid(
                row=0,
                column=4,
            )
            last_win_header_separator = tk.Frame(
                column_header,
                bg="#343B36",
                width=self._px(1),
            )
            last_win_header_separator.grid(
                row=0,
                column=3,
                sticky="ns",
                pady=self._px(5),
            )
            self.last_win_header_labels.append(last_win_heading)
            self.last_win_header_separators.append(last_win_header_separator)
            tk.Label(
                column_header,
                text="БМ",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            ).grid(
                row=0,
                column=2,
            )
        tk.Frame(list_shell, bg="#343B36", height=self._px(1)).pack(fill="x")

        list_body = tk.Frame(list_shell, bg=SURFACE)
        list_body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            list_body, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            list_body, orient="vertical", command=self.canvas.yview
        )
        self._scrollbar_visible = False
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_frame.grid_columnconfigure(0, weight=1, uniform="participants")
        self.rows_frame.grid_columnconfigure(1, weight=1, uniform="participants")
        self.rows_window = self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)

        influence_row = tk.Frame(
            self,
            bg=PANEL_BACKGROUND,
            height=self._px(34),
        )
        self.influence_row = influence_row
        influence_row.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(11), self._px(17)),
        )

        selection_controls = tk.Frame(influence_row, bg=PANEL_BACKGROUND)
        selection_controls.pack(side="left")
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_check = StyledCheckbutton(
            selection_controls,
            variable=self.select_all_var,
            background=PANEL_BACKGROUND,
        )
        self.select_all_check.pack(side="left")
        self.select_all_label = tk.Label(
            selection_controls,
            text="Выбрать всех",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        self.select_all_label.pack(side="left", padx=(self._px(8), 0))
        self.select_all_label.bind("<Button-1>", self._toggle_select_all_label)
        self.clear_selection_button = tk.Label(
            selection_controls,
            text="Убрать выделение",
            bg=PANEL_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 10),
            cursor="hand2",
            padx=self._px(2),
            pady=self._px(5),
        )
        self.clear_selection_button.pack(
            side="left", padx=(self._px(16), 0)
        )
        self.clear_selection_button.bind(
            "<Button-1>", lambda _event: self._clear_selection()
        )
        self.clear_selection_button.bind(
            "<Enter>", self._on_clear_selection_enter
        )
        self.clear_selection_button.bind(
            "<Leave>", self._on_clear_selection_leave
        )
        influence_row.pack_propagate(False)
        self.apply_penalty_controls = tk.Frame(
            selection_controls,
            bg=PANEL_BACKGROUND,
        )
        self.apply_penalty_controls.pack(side="left")
        tk.Frame(
            self.apply_penalty_controls,
            bg=BORDER,
            width=self._px(1),
        ).pack(
            side="left",
            fill="y",
            padx=(self._px(16), self._px(12)),
            pady=self._px(2),
        )
        self.apply_penalty_var = tk.BooleanVar(value=True)
        self.apply_penalty_check = StyledCheckbutton(
            self.apply_penalty_controls,
            variable=self.apply_penalty_var,
            background=PANEL_BACKGROUND,
        )
        self.apply_penalty_check.pack(side="left")
        self.apply_penalty_label = tk.Label(
            self.apply_penalty_controls,
            text="Применять штраф",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        self.apply_penalty_label.pack(side="left", padx=(self._px(8), 0))
        self.apply_penalty_label.bind("<Button-1>", self._toggle_apply_penalty)
        self.apply_penalty_var.trace_add(
            "write",
            self._on_apply_penalty_changed,
        )
        self.select_all_var.trace_add("write", self._on_select_all_changed)

        bm_controls = tk.Frame(influence_row, bg=PANEL_BACKGROUND)
        self.bm_controls = bm_controls
        bm_controls.pack(side="right", fill="y")
        self.penalty_settings_controls = tk.Frame(
            bm_controls,
            bg=PANEL_BACKGROUND,
        )
        self.penalty_settings_controls.pack(side="left", fill="y")
        self.penalty_button = styled_button(
            self.penalty_settings_controls,
            "Штрафы победителей",
            self._open_penalty_settings,
            SURFACE_LIGHT,
            TEXT,
        )
        self.penalty_button.pack(side="left")
        tk.Frame(
            self.penalty_settings_controls,
            bg=BORDER,
            width=self._px(1),
        ).pack(
            side="left",
            fill="y",
            padx=(self._px(12), self._px(18)),
            pady=self._px(2),
        )

        influence_label = tk.Label(
            bm_controls,
            text="% влияния БМ на вероятность",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
        )
        self.influence_entry = tk.Entry(
            bm_controls,
            textvariable=self.influence_var,
            width=7,
            justify="center",
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=INPUT_BACKGROUND,
            disabledforeground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(self.influence_entry)
        self.influence_entry.pack(side="right", ipady=self._px(6))
        influence_label.pack(side="right", padx=(0, self._px(10)))

    def set_mass_distribution_mode(self, enabled: bool) -> None:
        """Adapt shared participant controls to the selected application mode."""

        if enabled != self._mass_distribution_mode:
            self._switch_selection_mode(enabled)
        self._mass_distribution_mode = enabled
        self._hide_last_win_tooltip()
        if enabled:
            self.apply_penalty_controls.pack_forget()
            self.bm_controls.pack_forget()
            self.history_separator.pack_forget()
            self.history_button.pack_forget()
            if not self.distribution_header_separator.winfo_manager():
                self.distribution_header_separator.pack(
                    side="right", fill="y", padx=self._px(12), pady=self._px(2),
                )
            if not self.distribution_header_controls.winfo_manager():
                self.distribution_header_controls.pack(side="right")
            self.mass_distribution_button.configure(
                text="К розыгрышу",
                command=self.owner.show_draw_mode,
            )
            for label in self.last_win_header_labels:
                label.configure(text="УЧАСТИЯ / ВЫДАЧИ")
                label.grid_configure(
                    sticky="w",
                    padx=(self._px(10), 0),
                )
            for separator in self.last_win_header_separators:
                separator.configure(bg="#343B36")
        else:
            self.distribution_header_controls.pack_forget()
            self.distribution_header_separator.pack_forget()
            if not self.apply_penalty_controls.winfo_manager():
                self.apply_penalty_controls.pack(side="left")
            if not self.bm_controls.winfo_manager():
                self.bm_controls.pack(side="right", fill="y")
            if not self.history_separator.winfo_manager():
                self.history_separator.pack(
                    side="right",
                    fill="y",
                    padx=self._px(12),
                    pady=self._px(2),
                )
            if not self.history_button.winfo_manager():
                self.history_button.pack(side="right")
            self.mass_distribution_button.configure(
                text="Массовое распределение",
                command=self.owner.show_mass_distribution,
            )
            for label in self.last_win_header_labels:
                label.configure(text="ПОСЛЕДНЯЯ ПОБЕДА")
                label.grid_configure(sticky="", padx=0)
            for separator in self.last_win_header_separators:
                separator.configure(bg="#343B36")
        for row_data in self.rows:
            self._update_row_last_win(row_data)
        self._update_distribution_selection_controls()

    def _switch_selection_mode(self, mass_distribution: bool) -> None:
        if not mass_distribution:
            self._store_distribution_selection()
        self._bulk_selection = True
        try:
            for row_data in self.rows:
                enabled_var = row_data.get("enabled")
                if not isinstance(enabled_var, tk.BooleanVar):
                    continue
                if mass_distribution:
                    row_data["draw_enabled"] = enabled_var.get()
                else:
                    enabled_var.set(bool(row_data.get("draw_enabled", False)))
        finally:
            self._bulk_selection = False
        if mass_distribution:
            self._load_distribution_selection()
        self._refresh_select_all_state()

    def select_distribution_event(
        self,
        event_key: tuple[str, str] | None,
    ) -> None:
        """Show and edit the participant selection belonging to one event."""

        self._store_distribution_selection()
        self._active_distribution_event_key = event_key
        if self._mass_distribution_mode:
            self._load_distribution_selection()
            self._notify_distribution_participants_changed()
            self._update_distribution_selection_controls()
            for row in self.rows:
                self._update_row_last_win(row)
        if event_key is not None:
            self._start_distribution_border_pulse()

    def _store_distribution_selection(self) -> None:
        event_key = self._active_distribution_event_key
        if event_key is None or not self._mass_distribution_mode:
            return
        for row_data in self.rows:
            enabled_var = row_data.get("enabled")
            selections = row_data.setdefault("distribution_enabled", {})
            if isinstance(enabled_var, tk.BooleanVar) and isinstance(selections, dict):
                selections[event_key] = enabled_var.get()

    def _load_distribution_selection(self) -> None:
        event_key = self._active_distribution_event_key
        self._bulk_selection = True
        try:
            for row_data in self.rows:
                enabled_var = row_data.get("enabled")
                selections = row_data.get("distribution_enabled")
                if not isinstance(enabled_var, tk.BooleanVar):
                    continue
                selected = (
                    bool(selections.get(event_key, False))
                    if event_key is not None and isinstance(selections, dict)
                    else False
                )
                enabled_var.set(selected)
        finally:
            self._bulk_selection = False
        self._refresh_select_all_state()

    def distribution_participant_names(
        self,
        event_key: tuple[str, str],
    ) -> list[str]:
        names: list[str] = []
        for row_data in self.rows:
            name_var = row_data.get("name")
            enabled_var = row_data.get("enabled")
            selections = row_data.get("distribution_enabled")
            if not isinstance(name_var, tk.StringVar):
                continue
            selected = (
                enabled_var.get()
                if (
                    self._mass_distribution_mode
                    and event_key == self._active_distribution_event_key
                    and isinstance(enabled_var, tk.BooleanVar)
                )
                else bool(selections.get(event_key, False))
                if isinstance(selections, dict)
                else False
            )
            name = clean_nickname(name_var.get())
            if selected and name:
                names.append(name)
        return names

    def apply_distribution_participants_text(
        self,
        event_key: tuple[str, str],
        text: str,
    ) -> list[str]:
        """Apply a copied comma/newline separated roster to one event only."""

        requested_names = {
            nickname_lookup_key(part)
            for part in re.split(r"[,;\n\r\t]+", text)
            if nickname_lookup_key(part)
        }
        for row_data in self.rows:
            name_var = row_data.get("name")
            if not isinstance(name_var, tk.StringVar):
                continue
            selections = row_data.setdefault("distribution_enabled", {})
            if not isinstance(selections, dict):
                continue
            selections[event_key] = (
                nickname_lookup_key(name_var.get()) in requested_names
            )

        if (
            self._mass_distribution_mode
            and self._active_distribution_event_key == event_key
        ):
            self._load_distribution_selection()
        self._notify_distribution_event_participants_changed(event_key)
        return self.distribution_participant_names(event_key)

    def _notify_distribution_participants_changed(self) -> None:
        event_key = getattr(self, "_active_distribution_event_key", None)
        if event_key is not None:
            self._notify_distribution_event_participants_changed(event_key)

    def _notify_distribution_event_participants_changed(
        self,
        event_key: tuple[str, str],
    ) -> None:
        owner = getattr(self, "owner", None)
        callback = getattr(owner, "update_distribution_event_participants", None)
        if not callable(callback):
            return
        callback(event_key, self.distribution_participant_names(event_key))

    def _update_distribution_selection_controls(self) -> None:
        enabled = (
            not self._mass_distribution_mode
            or self._active_distribution_event_key is not None
        )
        state = "normal" if enabled else "disabled"
        self.select_all_check.configure(state=state)
        self.select_all_label.configure(
            fg=TEXT if enabled else DISABLED_TEXT,
            cursor="hand2" if enabled else "arrow",
        )
        self.clear_selection_button.configure(
            fg=MUTED if enabled else DISABLED_TEXT,
            cursor="hand2" if enabled else "arrow",
        )
        for row_data in self.rows:
            check = row_data.get("check")
            if isinstance(check, StyledCheckbutton):
                check.configure(state=state)

    @staticmethod
    def _blend_border_color(start: str, end: str, amount: float) -> str:
        start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
        end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
        blended = tuple(
            round(left + (right - left) * amount)
            for left, right in zip(start_rgb, end_rgb)
        )
        return "#" + "".join(f"{component:02X}" for component in blended)

    def _start_distribution_border_pulse(self) -> None:
        if self._distribution_pulse_after_id is not None:
            try:
                self.after_cancel(self._distribution_pulse_after_id)
            except tk.TclError:
                pass
        self._distribution_pulse_step = 0
        self._animate_distribution_border()

    def _animate_distribution_border(self) -> None:
        steps = 25
        amount = math.sin(math.pi * self._distribution_pulse_step / (steps - 1))
        color = self._blend_border_color(BORDER, ACCENT, amount)
        self.list_shell.configure(
            highlightbackground=color,
            highlightcolor=color,
        )
        self._distribution_pulse_step += 1
        if self._distribution_pulse_step < steps:
            self._distribution_pulse_after_id = self.after(
                32,
                self._animate_distribution_border,
            )
            return
        self._distribution_pulse_after_id = None
        self.list_shell.configure(
            highlightbackground=BORDER,
            highlightcolor=BORDER,
        )

    def _update_row_last_win(self, row_data: dict[str, object]) -> None:
        name_var = row_data.get("name")
        primary = row_data.get("last_win_primary")
        secondary = row_data.get("last_win_secondary")
        if not (
            isinstance(name_var, tk.StringVar)
            and isinstance(primary, tk.Label)
            and isinstance(secondary, tk.Label)
        ):
            return

        if self._mass_distribution_mode:
            event_key = self._active_distribution_event_key
            statistics_callback = getattr(self.owner, "distribution_statistics_for", None)
            if callable(statistics_callback):
                participations, allocations = statistics_callback(
                    event_key[0] if event_key is not None else None,
                    clean_nickname(name_var.get()),
                )
                primary.configure(
                    text=f"{participations} / {allocations}",
                    fg=MUTED,
                    font=("Segoe UI Semibold", 9),
                )
                primary.place(relx=0.0, rely=0.5, anchor="w")
            else:
                primary.configure(text="", fg=MUTED)
                primary.place_forget()
            secondary.place_forget()
            return

        player_name = clean_nickname(name_var.get())
        info = self._last_win_statistics.get(player_name)
        if info is None:
            primary.configure(text="Никогда", fg=MUTED)
            primary.place(relx=0.0, rely=0.5, anchor="w")
            secondary.place_forget()
            return

        font_size = 9 if info.draws_ago < 100 else (8 if info.draws_ago < 1000 else 7)
        primary.configure(
            text=format_draws_ago(info.draws_ago),
            fg=(
                DANGER
                if not self._mass_distribution_mode
                and player_name in self._penalty_statuses
                else ACCENT_HOVER
            ),
            font=("Segoe UI Semibold", font_size),
        )
        primary.place(relx=0.0, rely=0.5, anchor="w")
        secondary.place_forget()

    def _show_last_win_tooltip(
        self, row_data: dict[str, object], _event: tk.Event[tk.Misc]
    ) -> None:
        if self._mass_distribution_mode:
            return
        name_var = row_data.get("name")
        row = row_data.get("frame")
        last_win = row_data.get("last_win")
        if not (
            isinstance(name_var, tk.StringVar)
            and isinstance(row, tk.Frame)
            and isinstance(last_win, tk.Frame)
        ):
            return
        player_name = clean_nickname(name_var.get())
        result = self._last_win_results.get(player_name)
        if result is None:
            return

        self._cancel_last_win_tooltip_hide()
        tooltip = self._last_win_tooltip
        if (
            tooltip is not None
            and tooltip.winfo_exists()
            and self._last_win_tooltip_anchor is last_win
        ):
            tooltip.lift()
            return

        self._hide_last_win_tooltip()
        tooltip = tk.Toplevel(self)
        tooltip.withdraw()
        tooltip.wm_overrideredirect(True)
        try:
            tooltip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tooltip.configure(bg=BORDER)
        details = tk.Frame(
            tooltip,
            bg=SURFACE_LIGHT,
            padx=self._px(10),
            pady=self._px(7),
        )
        details.pack(padx=1, pady=1)
        tk.Label(
            details,
            text=format_draw_timestamp(result.timestamp),
            bg=SURFACE_LIGHT,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            details,
            text=result.reward,
            bg=SURFACE_LIGHT,
            fg=TEXT,
            font=("Segoe UI Semibold", 9),
            anchor="w",
            justify="left",
            wraplength=self._px(240),
        ).pack(fill="x", pady=(self._px(2), 0))
        penalty = (
            None
            if self._mass_distribution_mode
            else self._penalty_statuses.get(player_name)
        )
        if penalty is not None:
            tk.Frame(
                details,
                bg=BORDER,
                height=self._px(1),
            ).pack(fill="x", pady=(self._px(7), self._px(5)))
            tk.Label(
                details,
                text=(
                    "Коэффициент: "
                    f"{format_penalty_coefficient(penalty.coefficient)}"
                ),
                bg=SURFACE_LIGHT,
                fg=DANGER,
                font=("Segoe UI Semibold", 9),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                details,
                text=(
                    "До снятия штрафа: "
                    f"{format_remaining_draws(penalty.remaining_participations)}"
                ),
                bg=SURFACE_LIGHT,
                fg=MUTED,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(fill="x", pady=(self._px(2), 0))
        self._last_win_tooltip = tooltip
        self._last_win_tooltip_anchor = last_win
        def hide_tooltip_on_enter(widget: tk.Misc) -> None:
            widget.bind(
                "<Enter>",
                lambda _event: self._hide_last_win_tooltip(),
                add="+",
            )
            for child in widget.winfo_children():
                hide_tooltip_on_enter(child)

        # The panel covers rows below it.  It intentionally closes as soon as
        # the pointer reaches it, so their own last-win cells stay available.
        hide_tooltip_on_enter(tooltip)
        tooltip.update_idletasks()
        width = tooltip.winfo_reqwidth()
        height = tooltip.winfo_reqheight()
        row.update_idletasks()
        row_right = row.winfo_rootx() + row.winfo_width()
        x = row_right - width
        x = max(0, min(x, tooltip.winfo_screenwidth() - width))
        y = row.winfo_rooty() + row.winfo_height()
        tooltip.geometry(f"{width}x{height}+{x}+{y}")
        tooltip.deiconify()
        tooltip.lift()

    def _hide_last_win_tooltip(self) -> None:
        self._cancel_last_win_tooltip_hide()
        tooltip = getattr(self, "_last_win_tooltip", None)
        self._last_win_tooltip = None
        self._last_win_tooltip_anchor = None
        if tooltip is not None and tooltip.winfo_exists():
            tooltip.destroy()

    def _cancel_last_win_tooltip_hide(self) -> None:
        job = getattr(self, "_last_win_tooltip_hide_job", None)
        self._last_win_tooltip_hide_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass

    def _schedule_last_win_tooltip_hide(self, last_win: tk.Widget) -> None:
        self._cancel_last_win_tooltip_hide()
        self._last_win_tooltip_hide_job = self.after(
            80,
            lambda: self._hide_last_win_tooltip_if_left(last_win),
        )

    def _hide_last_win_tooltip_if_left(self, last_win: tk.Widget) -> None:
        self._last_win_tooltip_hide_job = None
        pointer_x, pointer_y = self.winfo_pointerxy()
        widget = self.winfo_containing(pointer_x, pointer_y)
        while widget is not None:
            if widget is last_win:
                return
            widget = widget.master
        self._hide_last_win_tooltip()

    def _add_row(
        self,
        name: str = "",
        enabled: bool = True,
        bm: float = 0.0,
        scroll_to_end: bool = True,
    ) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        content = tk.Frame(
            row, bg=SURFACE, padx=self._px(10), pady=0
        )
        content.pack(fill="x")
        content.grid_columnconfigure(2, weight=1)
        content.grid_columnconfigure(5, minsize=self._px(140))
        separator = tk.Frame(row, bg="#343B36", height=self._px(1))
        separator.pack(fill="x", padx=self._px(8))

        selection_strip = tk.Frame(
            content,
            bg=ACCENT if enabled else SURFACE,
            width=self._px(3),
        )
        selection_strip.grid(
            row=0,
            column=0,
            sticky="ns",
            padx=(0, self._px(7)),
        )
        selection_strip.pack_propagate(False)

        enabled_var = tk.BooleanVar(value=enabled)
        check = StyledCheckbutton(
            content,
            variable=enabled_var,
            background=SURFACE,
        )
        check.grid(row=0, column=1, padx=(0, self._px(10)))

        name_var = tk.StringVar(value=name)
        entry = tk.Entry(
            content,
            textvariable=name_var,
            width=8,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=SURFACE,
            disabledforeground=TEXT,
            relief="flat",
            font=("Segoe UI", 11),
            highlightthickness=0,
            highlightbackground=SURFACE,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(entry)
        entry.grid(
            row=0,
            column=2,
            sticky="ew",
            ipady=self._px(2),
        )

        bm_text = format_bm(bm)
        bm_var = tk.StringVar(value=bm_text)
        bm_entry = tk.Entry(
            content,
            textvariable=bm_var,
            width=9,
            justify="right",
            bg=SURFACE,
            fg=MUTED,
            insertbackground=TEXT,
            disabledbackground=SURFACE,
            disabledforeground=MUTED,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=0,
            highlightbackground=SURFACE,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(bm_entry)
        bm_entry.grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(self._px(12), self._px(10)),
            ipady=self._px(3),
        )

        row_data: dict[str, object] = {
            "frame": row,
            "content": content,
            "name": name_var,
            "name_entry": entry,
            "enabled": enabled_var,
            "bm": bm_var,
            "bm_entry": bm_entry,
            "check": check,
            "selection_strip": selection_strip,
            "separator": separator,
            "hovered": False,
        }
        if self._mass_distribution_mode:
            row_data["draw_enabled"] = False
            row_data["distribution_enabled"] = {}
            if self._active_distribution_event_key is not None:
                selections = row_data["distribution_enabled"]
                assert isinstance(selections, dict)
                selections[self._active_distribution_event_key] = enabled
        delete = StyledDeleteButton(
            content,
            command=lambda data=row_data: self._delete_row(data),
            background=SURFACE,
        )
        row_data["delete"] = delete
        delete.grid(row=0, column=6, padx=(self._px(8), 0))

        last_win_separator = tk.Frame(
            content,
            bg="#343B36",
            width=self._px(1),
        )
        last_win_separator.grid(
            row=0,
            column=4,
            sticky="ns",
            pady=self._px(4),
        )

        last_win = tk.Frame(
            content,
            bg=SURFACE,
            width=self._px(140),
            height=self._px(32),
        )
        last_win.grid(
            row=0,
            column=5,
            sticky="nsew",
            padx=(self._px(4), 0),
        )
        last_win.grid_propagate(False)
        last_win.grid_rowconfigure(0, weight=1)
        last_win.grid_columnconfigure(0, weight=1)
        last_win_text = tk.Frame(last_win, bg=SURFACE)
        last_win_text.grid(row=0, column=0, sticky="nsew")
        last_win_primary = tk.Label(
            last_win_text,
            text="Никогда",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
            anchor="w",
        )
        last_win_secondary = tk.Label(
            last_win_text,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 6),
            anchor="w",
        )
        row_data.update(
            {
                "last_win": last_win,
                "last_win_separator": last_win_separator,
                "last_win_text": last_win_text,
                "last_win_primary": last_win_primary,
                "last_win_secondary": last_win_secondary,
            }
        )
        self._update_row_last_win(row_data)
        for widget in (
            last_win,
            last_win_text,
            last_win_primary,
            last_win_secondary,
        ):
            widget.bind(
                "<Enter>",
                lambda event, data=row_data: self._show_last_win_tooltip(data, event),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event, cell=last_win: (
                    self._schedule_last_win_tooltip_hide(cell)
                ),
                add="+",
            )
        self.rows.append(row_data)
        self._place_row(row_data, len(self.rows) - 1)
        self._refresh_select_all_state()
        self._update_guild_count()

        name_var.trace_add("write", self._on_text_value_changed)
        name_var.trace_add(
            "write", lambda *_args, data=row_data: self._update_row_last_win(data)
        )
        name_var.trace_add(
            "write",
            lambda *_args: self._notify_distribution_participants_changed(),
        )
        bm_var.trace_add("write", self._on_text_value_changed)
        enabled_var.trace_add("write", self._on_toggle_value_changed)
        enabled_var.trace_add(
            "write", lambda *_args, data=row_data: self._update_row_selection(data)
        )
        self._update_row_selection(row_data)
        if (
            self._mass_distribution_mode
            and self._active_distribution_event_key is None
        ):
            check.configure(state="disabled")
        entry.bind("<FocusIn>", self._on_entry_focus_in, add="+")
        entry.bind("<FocusOut>", self._on_entry_focus_out, add="+")
        bm_entry.bind("<FocusIn>", self._on_entry_focus_in, add="+")
        bm_entry.bind("<FocusOut>", self._on_entry_focus_out, add="+")

        hover_widgets = (
            row,
            content,
            selection_strip,
            check,
            entry,
            bm_entry,
            last_win_separator,
            last_win,
            last_win_text,
            last_win_primary,
            last_win_secondary,
            delete,
        )
        for widget in hover_widgets:
            widget.bind(
                "<Enter>",
                lambda _event, data=row_data: self._set_row_hover(data, True),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event, data=row_data: self.after_idle(
                    lambda item=data: self._finish_row_leave(item)
                ),
                add="+",
            )
            widget.bind("<MouseWheel>", self._scroll)

        if not name:
            entry.focus_set()
        if scroll_to_end:
            self.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def _add_empty_row(self) -> None:
        self._add_row()

    def _delete_row(self, row_data: dict[str, object]) -> None:
        name_var = row_data.get("name")
        name = name_var.get().strip() if isinstance(name_var, tk.StringVar) else ""
        participant_caption = f"«{name}»" if name else "этого участника"
        confirmed = messagebox.askyesno(
            "Удаление участника",
            (
                f"Удалить {participant_caption} из общего списка?\n\n"
                "Это действие нельзя отменить."
            ),
            icon="warning",
            parent=self,
        )
        if not confirmed:
            return
        self._hide_last_win_tooltip()
        frame = row_data["frame"]
        if isinstance(frame, tk.Widget):
            frame.destroy()
        self.rows.remove(row_data)
        self._reflow_rows()
        self._refresh_select_all_state()
        self._update_guild_count()
        self._notify_distribution_participants_changed()
        self._schedule_auto_save(0)

    def _place_row(self, row_data: dict[str, object], index: int) -> None:
        frame = row_data.get("frame")
        if not isinstance(frame, tk.Widget):
            return
        frame.grid(
            row=index // 2,
            column=index % 2,
            sticky="ew",
            padx=(self._px(6), self._px(3))
            if index % 2 == 0
            else (self._px(3), self._px(6)),
        )

    def _reflow_rows(self) -> None:
        self._hide_last_win_tooltip()
        for index, row_data in enumerate(self.rows):
            self._place_row(row_data, index)

    def _sort_rows_by_bm(self) -> None:
        """Sort rows by BM and lay them out left-to-right, then top-to-bottom."""

        def row_key(row_data: dict[str, object]) -> tuple[int, float]:
            name_var = row_data.get("name")
            bm_var = row_data.get("bm")
            name = name_var.get().strip() if isinstance(name_var, tk.StringVar) else ""
            try:
                bm = parse_bm(bm_var.get()) if isinstance(bm_var, tk.StringVar) else 0.0
            except ValueError:
                return (1, 0.0)
            if not name or not math.isfinite(bm) or bm < 0:
                return (1, 0.0)
            return (0, -bm)

        ordered_rows = sorted(self.rows, key=row_key)
        if ordered_rows == self.rows:
            return
        self.rows[:] = ordered_rows
        for row_data in self.rows:
            frame = row_data.get("frame")
            if isinstance(frame, tk.Widget):
                frame.grid_forget()
        self._reflow_rows()

    def _update_guild_count(self) -> None:
        self.guild_count_label.configure(text=f"· {len(self.rows)}")

    def _update_row_selection(self, row_data: dict[str, object]) -> None:
        enabled_var = row_data.get("enabled")
        frame = row_data.get("frame")
        content = row_data.get("content")
        strip = row_data.get("selection_strip")
        check = row_data.get("check")
        name_entry = row_data.get("name_entry")
        bm_entry = row_data.get("bm_entry")
        delete = row_data.get("delete")
        last_win_separator = row_data.get("last_win_separator")
        last_win_widgets = (
            row_data.get("last_win"),
            row_data.get("last_win_text"),
            row_data.get("last_win_primary"),
            row_data.get("last_win_secondary"),
        )
        if not isinstance(enabled_var, tk.BooleanVar):
            return
        hovered = bool(row_data.get("hovered"))
        if enabled_var.get():
            background = ROW_SELECTED_HOVER if hovered else ROW_SELECTED
        else:
            background = ROW_HOVER if hovered else SURFACE
        if isinstance(frame, tk.Frame):
            frame.configure(bg=background)
        if isinstance(content, tk.Frame):
            content.configure(bg=background)
        if isinstance(strip, tk.Frame):
            strip.configure(bg=ACCENT if enabled_var.get() else background)
        if isinstance(check, StyledCheckbutton):
            check.configure(bg=background)
        if isinstance(last_win_separator, tk.Frame):
            last_win_separator.configure(bg="#343B36")
        for widget in last_win_widgets:
            if isinstance(widget, (tk.Frame, tk.Label)):
                widget.configure(bg=background)
        for entry in (name_entry, bm_entry):
            if isinstance(entry, tk.Entry):
                normal_foreground = MUTED if entry is bm_entry else TEXT
                entry.configure(
                    disabledbackground=background,
                    disabledforeground=normal_foreground,
                )
                if entry.focus_get() is not entry:
                    entry.configure(
                        bg=background,
                        fg=normal_foreground,
                        highlightthickness=0,
                        highlightbackground=background,
                    )
        if isinstance(delete, StyledDeleteButton):
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

    def _set_row_hover(
        self, row_data: dict[str, object], hovered: bool
    ) -> None:
        if bool(row_data.get("hovered")) == hovered:
            return
        row_data["hovered"] = hovered
        self._update_row_selection(row_data)

    def _finish_row_leave(self, row_data: dict[str, object]) -> None:
        frame = row_data.get("frame")
        if not isinstance(frame, tk.Frame) or not frame.winfo_exists():
            return
        try:
            pointed = frame.winfo_containing(
                frame.winfo_pointerx(), frame.winfo_pointery()
            )
        except tk.TclError:
            pointed = None
        current = pointed
        while current is not None:
            if current is frame:
                return
            current = getattr(current, "master", None)
        self._set_row_hover(row_data, False)

    def _open_import(self) -> None:
        if self.import_dialog is not None and self.import_dialog.winfo_exists():
            self.import_dialog.deiconify()
            self.import_dialog.lift()
            self.import_dialog.focus_force()
            return
        self.import_dialog = ScreenshotImportDialog(self)

    def _open_history(self) -> None:
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog.refresh()
            self.history_dialog.deiconify()
            self.history_dialog.lift()
            self.history_dialog.focus_force()
            return
        self.history_dialog = DrawHistoryDialog(self)

    def _open_penalty_settings(self) -> None:
        if self.penalty_dialog is not None and self.penalty_dialog.winfo_exists():
            self.penalty_dialog.deiconify()
            self.penalty_dialog.lift()
            self.penalty_dialog.focus_force()
            return
        self.penalty_dialog = PenaltySettingsDialog(
            self,
            self.penalty_settings,
        )

    def apply_penalty_settings(self, settings: PenaltySettings) -> None:
        self.owner.set_penalty_settings(settings)
        self.penalty_settings = settings
        self.refresh_last_wins()
        self.owner._request_wheel_redraw()

    def refresh_history_dialog(self) -> None:
        self.refresh_last_wins()
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog.refresh()

    def apply_import(self, participants: list[Participant]) -> None:
        existing: dict[str, dict[str, object]] = {}
        for row in self.rows:
            name_var = row.get("name")
            if isinstance(name_var, tk.StringVar):
                key = nickname_lookup_key(name_var.get())
                if key:
                    existing[key] = row

        for participant in participants:
            key = nickname_lookup_key(participant.name)
            if not key:
                continue
            row = existing.get(key)
            if row is None:
                self._add_row(participant.name, False, participant.bm)
                existing[key] = self.rows[-1]
                continue
            bm_var = row.get("bm")
            if isinstance(bm_var, tk.StringVar):
                bm_var.set(format_bm(participant.bm))
        self._schedule_auto_save(0)

    def _on_text_value_changed(self, *_args: object) -> None:
        self._schedule_auto_save(450)

    def _on_toggle_value_changed(self, *_args: object) -> None:
        if self._bulk_selection:
            return
        self._release_entry_focus()
        self._refresh_select_all_state()
        if self._mass_distribution_mode:
            self._store_distribution_selection()
            self._notify_distribution_participants_changed()
            return
        self._schedule_auto_save(self.SELECTION_UPDATE_DELAY_MS)

    def _on_select_all_changed(self, *_args: object) -> None:
        if self._syncing_select_all:
            return
        self._set_all_enabled(self.select_all_var.get())

    def _toggle_select_all_label(self, _event: tk.Event[tk.Misc]) -> str:
        if str(self.select_all_check.cget("state")) != "disabled":
            self.select_all_var.set(not self.select_all_var.get())
        return "break"

    def _clear_selection(self) -> None:
        if self.owner.spinning:
            return
        if (
            self._mass_distribution_mode
            and self._active_distribution_event_key is None
        ):
            return
        self._set_all_enabled(False)

    def _on_clear_selection_enter(self, _event: tk.Event[tk.Misc]) -> None:
        enabled = (
            not self._mass_distribution_mode
            or self._active_distribution_event_key is not None
        )
        self.clear_selection_button.configure(
            fg=TEXT if enabled else DISABLED_TEXT
        )

    def _on_clear_selection_leave(self, _event: tk.Event[tk.Misc]) -> None:
        enabled = (
            not self._mass_distribution_mode
            or self._active_distribution_event_key is not None
        )
        self.clear_selection_button.configure(
            fg=MUTED if enabled else DISABLED_TEXT
        )

    def _set_all_enabled(self, enabled: bool) -> None:
        self._release_entry_focus()
        self._bulk_selection = True
        try:
            for row in self.rows:
                enabled_var = row.get("enabled")
                if isinstance(enabled_var, tk.BooleanVar):
                    enabled_var.set(enabled)
        finally:
            self._bulk_selection = False
        self._refresh_select_all_state()
        if self._mass_distribution_mode:
            self._store_distribution_selection()
            self._notify_distribution_participants_changed()
            return
        self._schedule_auto_save(self.SELECTION_UPDATE_DELAY_MS)

    def _refresh_select_all_state(self) -> None:
        enabled_values = [
            enabled_var.get()
            for row in self.rows
            if isinstance((enabled_var := row.get("enabled")), tk.BooleanVar)
        ]
        all_selected = bool(enabled_values) and all(enabled_values)
        if self.select_all_var.get() == all_selected:
            return
        self._syncing_select_all = True
        try:
            self.select_all_var.set(all_selected)
        finally:
            self._syncing_select_all = False

    def _on_entry_focus_in(self, event: tk.Event[tk.Misc]) -> None:
        if not isinstance(event.widget, tk.Entry):
            return
        event.widget.configure(
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER_LIGHT,
            highlightcolor=BORDER_LIGHT,
        )

    def _on_entry_focus_out(self, event: tk.Event[tk.Misc]) -> None:
        entry = event.widget
        if isinstance(entry, tk.Entry):
            for row in self.rows:
                if row.get("bm_entry") is entry:
                    bm_var = row.get("bm")
                    if isinstance(bm_var, tk.StringVar):
                        try:
                            formatted = format_bm(parse_bm(bm_var.get()))
                            if bm_var.get() != formatted:
                                bm_var.set(formatted)
                        except ValueError:
                            pass
                if row.get("bm_entry") is entry or row.get("name_entry") is entry:
                    self.after_idle(
                        lambda data=row: self._update_row_selection(data)
                    )
                    break
        self._schedule_auto_save(0)

    def _clear_entry_focus_on_enter(self, event: tk.Event[tk.Misc]) -> str | None:
        if not isinstance(event.widget, tk.Entry):
            return None
        if self._is_panel_widget(event.widget):
            self._schedule_auto_save(0)
        event.widget.winfo_toplevel().focus_set()
        return "break"

    def _clear_entry_focus_on_click(self, event: tk.Event[tk.Misc]) -> None:
        if self._focus_move_after_id is not None:
            self.after_cancel(self._focus_move_after_id)
            self._focus_move_after_id = None
        clicked = event.widget
        if isinstance(clicked, str):
            try:
                clicked = self.owner.nametowidget(clicked)
            except (KeyError, tk.TclError):
                # Native ttk popdown windows have no Python widget wrapper.
                return
        if not isinstance(clicked, tk.Misc):
            return
        try:
            focused = self.owner.focus_get()
        except (KeyError, tk.TclError):
            return
        if not isinstance(focused, tk.Entry) or clicked is focused:
            return
        if self._is_panel_widget(focused):
            self._schedule_auto_save(0)
        if isinstance(clicked, tk.Entry):
            return

        def move_focus() -> None:
            self._focus_move_after_id = None
            try:
                if clicked.winfo_exists():
                    clicked.focus_set()
            except (KeyError, tk.TclError):
                pass

        self._focus_move_after_id = self.after_idle(move_focus)

    def _release_entry_focus(self) -> None:
        try:
            focused = self.owner.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if isinstance(focused, tk.Entry) and self._is_panel_widget(focused):
            self._schedule_auto_save(0)
        try:
            self.owner.focus_set()
        except tk.TclError:
            pass

    def _on_owner_unmap(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.owner:
            return
        self._hide_last_win_tooltip()
        self._clear_focus_after_restore = True
        self._release_entry_focus()

    def _on_owner_map(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.owner or not self._clear_focus_after_restore:
            return
        self._clear_focus_after_restore = False
        self.after_idle(self._release_entry_focus)

    def _is_panel_widget(self, widget: tk.Misc) -> bool:
        current: tk.Misc | None = widget
        while current is not None:
            if current is self:
                return True
            current = getattr(current, "master", None)
        return False

    def _schedule_auto_save(self, delay_ms: int) -> None:
        if not self._auto_save_ready:
            return
        if self.owner.spinning:
            self._save_pending = True
            return
        if self._auto_save_after_id is not None:
            try:
                self.after_cancel(self._auto_save_after_id)
            except tk.TclError:
                pass
        self._auto_save_after_id = self.after(delay_ms, self._perform_auto_save)

    def _set_entry_valid(self, entry: tk.Entry, valid: bool) -> None:
        is_influence = entry is self.influence_entry
        focused = entry.focus_get() is entry
        color = BORDER if valid else DANGER
        focus_color = BORDER_LIGHT if valid else "#C46B68"
        entry.configure(
            highlightthickness=1 if is_influence or focused or not valid else 0,
            highlightbackground=color,
            highlightcolor=focus_color,
        )

    def _perform_auto_save(self) -> None:
        self._auto_save_after_id = None
        if self.owner.spinning:
            self._save_pending = True
            return

        try:
            influence_percent = float(
                self.influence_var.get().strip().replace(",", ".")
            )
        except ValueError:
            influence_percent = -1.0
        influence_valid = (
            math.isfinite(influence_percent)
            and 0 <= influence_percent <= 100
        )
        self._set_entry_valid(self.influence_entry, influence_valid)
        if not influence_valid:
            return

        participants: list[Participant] = []
        rows_valid = True
        for row in self.rows:
            name_var = row.get("name")
            enabled_var = row.get("enabled")
            bm_var = row.get("bm")
            bm_entry = row.get("bm_entry")
            if (
                not isinstance(name_var, tk.StringVar)
                or not isinstance(enabled_var, tk.BooleanVar)
                or not isinstance(bm_var, tk.StringVar)
                or not isinstance(bm_entry, tk.Entry)
            ):
                continue
            name = " ".join(name_var.get().strip().split())
            try:
                bm = parse_bm(bm_var.get())
            except ValueError:
                bm = -1.0
            bm_valid = math.isfinite(bm) and bm >= 0
            self._set_entry_valid(bm_entry, bm_valid)
            if not bm_valid:
                rows_valid = False
                continue
            if name:
                persisted_enabled = (
                    bool(row.get("draw_enabled", False))
                    if self._mass_distribution_mode
                    else enabled_var.get()
                )
                participants.append(Participant(name[:40], persisted_enabled, bm))

        if not rows_valid:
            return

        participants = sort_participants_by_bm(participants)
        try:
            focused_widget = self.owner.focus_get()
        except (KeyError, tk.TclError):
            focused_widget = None
        editing_bm = any(
            row.get("bm_entry") is focused_widget for row in self.rows
        )
        if not editing_bm:
            self._sort_rows_by_bm()

        if (
            participants == self.owner.participants
            and math.isclose(influence_percent, self.owner.bm_influence_percent)
        ):
            self._save_pending = False
            return

        try:
            self.owner.set_participants(participants, influence_percent)
        except OSError as error:
            error_text = str(error)
            if error_text != self._last_save_error:
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось сохранить список:\n{error}",
                    parent=self,
                )
                self._last_save_error = error_text
            return

        self._last_save_error = ""
        self._save_pending = False

    def flush_auto_save(self) -> None:
        if self._auto_save_after_id is None and not self._save_pending:
            return
        if self._auto_save_after_id is not None:
            try:
                self.after_cancel(self._auto_save_after_id)
            except tk.TclError:
                pass
            self._auto_save_after_id = None
        self._perform_auto_save()

    def set_editing_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"

        def update_widgets(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if isinstance(
                    child,
                    (
                        tk.Button,
                        tk.Checkbutton,
                        tk.Entry,
                        StyledCheckbutton,
                        StyledDeleteButton,
                    ),
                ):
                    child.configure(state=state)
                update_widgets(child)

        update_widgets(self)
        if enabled and self._save_pending:
            self._schedule_auto_save(0)

    def destroy(self) -> None:
        self._hide_last_win_tooltip()
        for attribute in ("_focus_move_after_id", "_scroll_update_after_id"):
            job = getattr(self, attribute, None)
            if job is not None:
                self.after_cancel(job)
                setattr(self, attribute, None)
        if self._distribution_pulse_after_id is not None:
            try:
                self.after_cancel(self._distribution_pulse_after_id)
            except tk.TclError:
                pass
            self._distribution_pulse_after_id = None
        if self._auto_save_after_id is not None:
            try:
                self.after_cancel(self._auto_save_after_id)
            except tk.TclError:
                pass
            self._auto_save_after_id = None
        if self.import_dialog is not None and self.import_dialog.winfo_exists():
            self.import_dialog._close()
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog._close()
        if self.penalty_dialog is not None and self.penalty_dialog.winfo_exists():
            self.penalty_dialog._close()
        try:
            self.owner.unbind_all("<Button-1>")
            self.owner.unbind_all("<Return>")
            self.owner.unbind("<Unmap>", self._unmap_binding_id)
            self.owner.unbind("<Map>", self._map_binding_id)
        except tk.TclError:
            pass
        super().destroy()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self._schedule_scroll_update()

    def _schedule_scroll_update(self) -> None:
        if self._scroll_update_after_id is None:
            self._scroll_update_after_id = self.after_idle(self._run_scroll_update)

    def _run_scroll_update(self) -> None:
        self._scroll_update_after_id = None
        region = self.canvas.bbox("all")
        if region != self._scroll_region:
            self._scroll_region = region
            self.canvas.configure(scrollregion=region)
        self._update_scrollbar_visibility()

    def _resize_rows(self, event: tk.Event[tk.Misc]) -> None:
        if self._rows_canvas_width != event.width:
            self._rows_canvas_width = event.width
            self.canvas.itemconfigure(self.rows_window, width=event.width)
        self._schedule_scroll_update()

    def _update_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.canvas.winfo_height() + 1
        if should_show and not self._scrollbar_visible:
            self.scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
        elif not should_show and self._scrollbar_visible:
            self.canvas.yview_moveto(0.0)
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        self._hide_last_win_tooltip()
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"
