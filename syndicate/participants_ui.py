"""Editable two-column guild participant list and its controls."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, ttk

from .history_ui import DrawHistoryDialog
from .import_ui import ScreenshotImportDialog
from .models import (
    DrawResult,
    LastWinInfo,
    Participant,
    clean_nickname,
    format_bm,
    format_draw_timestamp,
    format_draws_ago,
    last_win_statistics,
    parse_bm,
    sort_participants_by_bm,
)
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
        self._auto_save_ready = False
        self._auto_save_after_id: str | None = None
        self._save_pending = False
        self._last_save_error = ""
        self._syncing_select_all = False
        self._bulk_selection = False
        self._clear_focus_after_restore = False
        self._last_win_statistics: dict[str, LastWinInfo] = {}
        self._last_win_results: dict[str, DrawResult] = {}
        self._last_win_tooltip: tk.Toplevel | None = None
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

    def _build_ui(self) -> None:
        heading = tk.Frame(self, bg=PANEL_BACKGROUND)
        heading.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(18), self._px(10)),
        )

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

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(fill="both", expand=True, padx=self._px(24))

        columns_header = tk.Frame(
            list_shell, bg=SURFACE, height=self._px(27)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        columns_header.grid_columnconfigure(0, weight=1, uniform="headers")
        columns_header.grid_columnconfigure(1, weight=1, uniform="headers")
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
            tk.Label(
                column_header,
                text="ПОСЛЕДНЯЯ ПОБЕДА",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 9),
            ).grid(
                row=0,
                column=4,
            )
            tk.Frame(
                column_header,
                bg="#343B36",
                width=self._px(1),
            ).grid(
                row=0,
                column=3,
                sticky="ns",
                pady=self._px(5),
            )
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

        influence_row = tk.Frame(self, bg=PANEL_BACKGROUND)
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
        select_all_label = tk.Label(
            selection_controls,
            text="Выбрать всех",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        select_all_label.pack(side="left", padx=(self._px(8), 0))
        select_all_label.bind("<Button-1>", self._toggle_select_all_label)
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
            "<Enter>", lambda _event: self.clear_selection_button.configure(fg=TEXT)
        )
        self.clear_selection_button.bind(
            "<Leave>", lambda _event: self.clear_selection_button.configure(fg=MUTED)
        )
        self.select_all_var.trace_add("write", self._on_select_all_changed)

        bm_controls = tk.Frame(influence_row, bg=PANEL_BACKGROUND)
        bm_controls.pack(side="right", fill="y")
        tk.Frame(
            bm_controls,
            bg=BORDER,
            width=self._px(1),
        ).pack(
            side="left",
            fill="y",
            padx=(0, self._px(18)),
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

        info = self._last_win_statistics.get(clean_nickname(name_var.get()))
        if info is None:
            primary.configure(text="Никогда", fg=MUTED)
            primary.place(relx=0.0, rely=0.5, anchor="w")
            secondary.place_forget()
            return

        font_size = 9 if info.draws_ago < 100 else (8 if info.draws_ago < 1000 else 7)
        primary.configure(
            text=format_draws_ago(info.draws_ago),
            fg=ACCENT_HOVER,
            font=("Segoe UI Semibold", font_size),
        )
        primary.place(relx=0.0, rely=0.5, anchor="w")
        secondary.place_forget()

    def _show_last_win_tooltip(
        self, row_data: dict[str, object], event: tk.Event[tk.Misc]
    ) -> None:
        name_var = row_data.get("name")
        if not isinstance(name_var, tk.StringVar):
            return
        result = self._last_win_results.get(clean_nickname(name_var.get()))
        if result is None:
            return

        self._hide_last_win_tooltip()
        tooltip = tk.Toplevel(self)
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
        tooltip.geometry(
            f"+{event.x_root + self._px(12)}+{event.y_root + self._px(12)}"
        )
        self._last_win_tooltip = tooltip

    def _hide_last_win_tooltip(self) -> None:
        tooltip = self._last_win_tooltip
        self._last_win_tooltip = None
        if tooltip is not None and tooltip.winfo_exists():
            tooltip.destroy()

    def _hide_last_win_tooltip_if_left(self, last_win: tk.Widget) -> None:
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
                lambda _event, cell=last_win: self.after_idle(
                    lambda target=cell: self._hide_last_win_tooltip_if_left(target)
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
        bm_var.trace_add("write", self._on_text_value_changed)
        enabled_var.trace_add("write", self._on_toggle_value_changed)
        enabled_var.trace_add(
            "write", lambda *_args, data=row_data: self._update_row_selection(data)
        )
        self._update_row_selection(row_data)
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
        frame = row_data["frame"]
        if isinstance(frame, tk.Widget):
            frame.destroy()
        self.rows.remove(row_data)
        self._reflow_rows()
        self._refresh_select_all_state()
        self._update_guild_count()
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

    def refresh_history_dialog(self) -> None:
        self.refresh_last_wins()
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog.refresh()

    def apply_import(self, participants: list[Participant]) -> None:
        existing: dict[str, dict[str, object]] = {}
        for row in self.rows:
            name_var = row.get("name")
            if isinstance(name_var, tk.StringVar):
                existing[name_var.get().strip().casefold()] = row

        for participant in participants:
            row = existing.get(participant.name.casefold())
            if row is None:
                self._add_row(participant.name, False, participant.bm)
                continue
            bm_var = row.get("bm")
            if isinstance(bm_var, tk.StringVar):
                bm_var.set(format_bm(participant.bm))
        self._schedule_auto_save(0)

    def _on_text_value_changed(self, *_args: object) -> None:
        self._schedule_auto_save(250)

    def _on_toggle_value_changed(self, *_args: object) -> None:
        if self._bulk_selection:
            return
        self._release_entry_focus()
        self._refresh_select_all_state()
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
        self._set_all_enabled(False)

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
                            bm_var.set(format_bm(parse_bm(bm_var.get())))
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
        try:
            focused = self.owner.focus_get()
        except (KeyError, tk.TclError):
            return
        if not isinstance(focused, tk.Entry) or event.widget is focused:
            return
        if self._is_panel_widget(focused):
            self._schedule_auto_save(0)
        if isinstance(event.widget, tk.Entry):
            return

        def move_focus() -> None:
            try:
                if event.widget.winfo_exists():
                    event.widget.focus_set()
            except (KeyError, tk.TclError):
                pass

        self.after_idle(move_focus)

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
                participants.append(Participant(name[:40], enabled_var.get(), bm))

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
        try:
            self.owner.unbind_all("<Button-1>")
            self.owner.unbind_all("<Return>")
            self.owner.unbind("<Unmap>", self._unmap_binding_id)
            self.owner.unbind("<Map>", self._map_binding_id)
        except tk.TclError:
            pass
        super().destroy()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._update_scrollbar_visibility)

    def _resize_rows(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.rows_window, width=event.width)
        self.after_idle(self._update_scrollbar_visibility)

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
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"
