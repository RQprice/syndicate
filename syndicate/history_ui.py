"""Draw-history table and date-range picker UI."""
from __future__ import annotations

import calendar
import os
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from .models import DrawResult, draw_result_date, format_draw_timestamp
from .platform import (
    apply_dark_title_bar,
    apply_window_icon,
    enable_entry_shortcuts,
    keep_dark_title_bar,
)
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    APP_NAME,
    BORDER,
    BORDER_LIGHT,
    BRAND_GREEN,
    BRAND_GREEN_LIGHT,
    BUTTON_BORDER,
    BUTTON_HOVER,
    DISABLED_TEXT,
    INPUT_BACKGROUND,
    MUTED,
    PANEL_BACKGROUND,
    ROW_HOVER,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_BRIGHT,
)
from .widgets import StyledDeleteButton


class DateRangePicker(tk.Toplevel):
    MONTH_NAMES = (
        "ЯНВАРЬ",
        "ФЕВРАЛЬ",
        "МАРТ",
        "АПРЕЛЬ",
        "МАЙ",
        "ИЮНЬ",
        "ИЮЛЬ",
        "АВГУСТ",
        "СЕНТЯБРЬ",
        "ОКТЯБРЬ",
        "НОЯБРЬ",
        "ДЕКАБРЬ",
    )
    WEEKDAYS = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
    RANGE_BACKGROUND = "#38372D"

    def __init__(self, owner: "DrawHistoryDialog") -> None:
        super().__init__(owner)
        self.withdraw()
        self.owner = owner
        self.ui_scale = owner.ui_scale
        self.selected_start = owner.date_from
        self.selected_end = owner.date_to
        reference = self.selected_start or self._latest_result_date() or date.today()
        self.visible_month = reference.replace(day=1)
        self.day_cells: list[dict[str, object]] = []
        self._focus_after_id: str | None = None

        self.overrideredirect(True)
        self.configure(bg=BORDER_LIGHT)
        self.transient(owner)
        self.bind("<Escape>", lambda _event: self._close())
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self._build_ui()
        self._show_below_button()

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _latest_result_date(self) -> date | None:
        dates = [
            parsed
            for result in self.owner._results
            if (parsed := draw_result_date(result.timestamp)) is not None
        ]
        return max(dates) if dates else None

    def _build_ui(self) -> None:
        panel = tk.Frame(self, bg=PANEL_BACKGROUND)
        panel.pack(fill="both", expand=True, padx=self._px(1), pady=self._px(1))

        header = tk.Frame(panel, bg=PANEL_BACKGROUND)
        header.pack(fill="x", padx=self._px(14), pady=(self._px(12), self._px(8)))
        tk.Label(
            header,
            text="ПЕРИОД",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
        ).pack(side="left")
        close_button = StyledDeleteButton(
            header,
            command=self._close,
            background=PANEL_BACKGROUND,
        )
        close_button.pack(side="right")

        navigation = tk.Frame(panel, bg=PANEL_BACKGROUND)
        navigation.pack(fill="x", padx=self._px(14), pady=(0, self._px(8)))
        self._navigation_button(navigation, "‹", -1).pack(side="left")
        self.month_label = tk.Label(
            navigation,
            bg=PANEL_BACKGROUND,
            fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 11),
            anchor="center",
        )
        self.month_label.pack(side="left", fill="x", expand=True)
        self._navigation_button(navigation, "›", 1).pack(side="right")

        calendar_frame = tk.Frame(panel, bg=SURFACE)
        calendar_frame.pack(fill="both", expand=True, padx=self._px(14))
        for column in range(7):
            calendar_frame.grid_columnconfigure(column, weight=1, uniform="days")
        for column, weekday in enumerate(self.WEEKDAYS):
            tk.Label(
                calendar_frame,
                text=weekday,
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 8),
                pady=self._px(7),
            ).grid(row=0, column=column, sticky="nsew")

        for index in range(42):
            cell = tk.Label(
                calendar_frame,
                bg=SURFACE,
                fg=TEXT,
                font=("Segoe UI", 10),
                width=4,
                height=2,
                cursor="hand2",
                highlightthickness=1,
                highlightbackground=SURFACE,
            )
            cell.grid(
                row=index // 7 + 1,
                column=index % 7,
                sticky="nsew",
                padx=self._px(1),
                pady=self._px(1),
            )
            cell_data: dict[str, object] = {
                "widget": cell,
                "date": None,
                "hovered": False,
            }
            cell.bind(
                "<Button-1>",
                lambda _event, data=cell_data: self._select_day(data),
            )
            cell.bind(
                "<Enter>",
                lambda _event, data=cell_data: self._set_day_hover(data, True),
            )
            cell.bind(
                "<Leave>",
                lambda _event, data=cell_data: self._set_day_hover(data, False),
            )
            self.day_cells.append(cell_data)

        self.selection_label = tk.Label(
            panel,
            bg=PANEL_BACKGROUND,
            fg=ACCENT_HOVER,
            font=("Segoe UI Semibold", 10),
            anchor="center",
        )
        self.selection_label.pack(fill="x", padx=self._px(14), pady=self._px(10))

        footer = tk.Frame(panel, bg=PANEL_BACKGROUND)
        footer.pack(fill="x", padx=self._px(14), pady=(0, self._px(14)))
        self._action_button(
            footer,
            "Сбросить",
            self._clear,
            SURFACE_LIGHT,
            TEXT,
        ).pack(side="left")
        self.apply_button = self._action_button(
            footer,
            "Применить",
            self._apply,
            ACCENT,
            TEXT_BRIGHT,
        )
        self.apply_button.pack(side="right")
        self._redraw_calendar()

    def _navigation_button(
        self,
        parent: tk.Misc,
        text: str,
        offset: int,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=lambda: self._change_month(offset),
            bg=SURFACE_LIGHT,
            fg=TEXT,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_BRIGHT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BUTTON_BORDER,
            cursor="hand2",
            font=("Segoe UI Symbol", 13),
            padx=self._px(10),
            pady=self._px(1),
        )
        return button

    def _action_button(
        self,
        parent: tk.Misc,
        text: str,
        command: object,
        background: str,
        foreground: str,
    ) -> tk.Button:
        accent = background == ACCENT
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=ACCENT_HOVER if accent else BUTTON_HOVER,
            activeforeground=TEXT_BRIGHT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=ACCENT_DARK if accent else BUTTON_BORDER,
            disabledforeground=DISABLED_TEXT,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            padx=self._px(12),
            pady=self._px(6),
        )
        return button

    def _change_month(self, offset: int) -> None:
        month_index = self.visible_month.year * 12 + self.visible_month.month - 1
        month_index += offset
        year, month_zero_based = divmod(month_index, 12)
        self.visible_month = date(year, month_zero_based + 1, 1)
        self._redraw_calendar()

    def _select_day(self, cell_data: dict[str, object]) -> None:
        selected = cell_data.get("date")
        if not isinstance(selected, date):
            return
        if self.selected_start is None or self.selected_end is not None:
            self.selected_start = selected
            self.selected_end = None
        elif selected < self.selected_start:
            self.selected_end = self.selected_start
            self.selected_start = selected
        else:
            self.selected_end = selected
        self._redraw_calendar()

    def _set_day_hover(
        self,
        cell_data: dict[str, object],
        hovered: bool,
    ) -> None:
        cell_data["hovered"] = hovered
        self._style_day(cell_data)

    def _style_day(self, cell_data: dict[str, object]) -> None:
        widget = cell_data.get("widget")
        value = cell_data.get("date")
        if not isinstance(widget, tk.Label):
            return
        if not isinstance(value, date):
            widget.configure(
                text="",
                bg=SURFACE,
                highlightbackground=SURFACE,
                cursor="arrow",
            )
            return

        is_endpoint = value in (self.selected_start, self.selected_end)
        in_range = (
            self.selected_start is not None
            and self.selected_end is not None
            and self.selected_start <= value <= self.selected_end
        )
        if is_endpoint:
            background = ACCENT
            foreground = TEXT_BRIGHT
        elif in_range:
            background = self.RANGE_BACKGROUND
            foreground = TEXT_BRIGHT
        elif bool(cell_data.get("hovered")):
            background = ROW_HOVER
            foreground = TEXT_BRIGHT
        else:
            background = SURFACE
            foreground = TEXT
        widget.configure(
            text=str(value.day),
            bg=background,
            fg=foreground,
            cursor="hand2",
            highlightbackground=(
                BRAND_GREEN_LIGHT if value == date.today() else background
            ),
        )

    def _redraw_calendar(self) -> None:
        self.month_label.configure(
            text=f"{self.MONTH_NAMES[self.visible_month.month - 1]} {self.visible_month.year}"
        )
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
            self.visible_month.year,
            self.visible_month.month,
        )
        visible_dates = [value for week in weeks for value in week]
        for index, cell_data in enumerate(self.day_cells):
            value = visible_dates[index] if index < len(visible_dates) else None
            if value is not None and value.month != self.visible_month.month:
                value = None
            cell_data["date"] = value
            self._style_day(cell_data)

        if self.selected_start is None:
            selection_text = "Период не выбран"
        elif self.selected_end is None:
            selection_text = self.selected_start.strftime("%d.%m.%Y — …")
        else:
            selection_text = (
                f"{self.selected_start:%d.%m.%Y} — {self.selected_end:%d.%m.%Y}"
            )
        self.selection_label.configure(text=selection_text)
        self.apply_button.configure(
            state="normal" if self.selected_start is not None else "disabled",
            cursor="hand2" if self.selected_start is not None else "arrow",
        )

    def _apply(self) -> None:
        if self.selected_start is None:
            return
        end = self.selected_end or self.selected_start
        self.owner.set_date_filter(self.selected_start, end)
        self._close()

    def _clear(self) -> None:
        self.owner.set_date_filter(None, None)
        self._close()

    def _show_below_button(self) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        button = self.owner.calendar_button
        x = button.winfo_rootx() + button.winfo_width() - width
        y = button.winfo_rooty() + button.winfo_height() + self._px(6)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = min(max(0, x), max(0, screen_width - width))
        y = min(max(0, y), max(0, screen_height - height))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_focus_out(self, _event: tk.Event[tk.Misc]) -> None:
        if self._focus_after_id is not None:
            self.after_cancel(self._focus_after_id)
        self._focus_after_id = self.after(60, self._close_if_focus_lost)

    def _close_if_focus_lost(self) -> None:
        self._focus_after_id = None
        if not self.winfo_exists():
            return
        focused = self.focus_displayof()
        if focused is None or focused.winfo_toplevel() is not self:
            self._close(restore_focus=False)

    def _close(self, restore_focus: bool = True) -> None:
        if self._focus_after_id is not None:
            try:
                self.after_cancel(self._focus_after_id)
            except tk.TclError:
                pass
            self._focus_after_id = None
        if getattr(self.owner, "date_picker", None) is self:
            self.owner.date_picker = None
        self.destroy()
        if restore_focus:
            self.owner._schedule_focus_after_date_picker()


class DrawHistoryDialog(tk.Toplevel):
    def __init__(self, owner: "ParticipantsPanel") -> None:
        super().__init__(owner.winfo_toplevel())
        self.withdraw()
        self.owner = owner
        self.app = owner.owner
        self.ui_scale = float(getattr(owner, "ui_scale", 1.0))
        self._scrollbar_visible = False
        self._layout_after_id: str | None = None
        self._focus_restore_after_id: str | None = None
        self._center_after_id: str | None = None
        self._open_after_id: str | None = None
        self.search_var = tk.StringVar()
        self._results: list[DrawResult] = []
        self.date_from: date | None = None
        self.date_to: date | None = None
        self.date_picker: DateRangePicker | None = None
        self._calendar_hovered = False
        if os.name == "nt":
            self.attributes("-alpha", 0.0)

        self.title("История розыгрышей")
        apply_window_icon(self)
        self.geometry(f"{self._px(900)}x{self._px(580)}")
        self.minsize(self._px(720), self._px(420))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(owner.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._build_ui()
        self.search_var.trace_add("write", self._on_search_changed)
        self._center_after_id = self.after_idle(self._center_on_application)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _configure_columns(self, frame: tk.Misc) -> None:
        frame.grid_columnconfigure(0, weight=2, uniform="history_columns")
        frame.grid_columnconfigure(1, weight=7, uniform="history_columns")
        frame.grid_columnconfigure(
            2,
            weight=2,
            minsize=self._px(155),
            uniform="history_columns",
        )
        frame.grid_columnconfigure(3, weight=0, minsize=self._px(42))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=PANEL_BACKGROUND)
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(20), self._px(12)),
        )
        tk.Label(
            header,
            text="ИСТОРИЯ РОЗЫГРЫШЕЙ",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left")
        self.count_label = tk.Label(
            header,
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 12),
        )
        self.count_label.pack(
            side="left",
            padx=(self._px(8), 0),
            pady=(self._px(2), 0),
        )

        search_group = tk.Frame(header, bg=PANEL_BACKGROUND)
        search_group.pack(side="right", fill="y")
        tk.Label(
            search_group,
            text="ПОИСК",
            bg=PANEL_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left", padx=(0, self._px(9)))
        search_field = tk.Frame(
            search_group,
            bg=INPUT_BACKGROUND,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        search_field.pack(side="left", fill="y")
        self.search_entry = tk.Entry(
            search_field,
            textvariable=self.search_var,
            width=28,
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=BRAND_GREEN,
            selectforeground=TEXT_BRIGHT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
        )
        enable_entry_shortcuts(self.search_entry)
        self.search_entry.pack(
            fill="both",
            expand=True,
            padx=self._px(9),
            ipady=self._px(5),
        )
        self.search_entry.bind(
            "<FocusIn>",
            lambda _event: search_field.configure(
                highlightbackground=BORDER_LIGHT
            ),
            add="+",
        )
        self.search_entry.bind(
            "<FocusOut>",
            lambda _event: search_field.configure(highlightbackground=BORDER),
            add="+",
        )
        self.calendar_button = tk.Canvas(
            search_group,
            width=self._px(38),
            height=self._px(34),
            bg=PANEL_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.calendar_button.pack(side="left", padx=(self._px(8), 0))
        self.calendar_button.bind("<Button-1>", self._open_date_picker)
        self.calendar_button.bind("<Return>", self._open_date_picker)
        self.calendar_button.bind("<space>", self._open_date_picker)
        self.calendar_button.bind(
            "<Enter>", lambda _event: self._set_calendar_hover(True)
        )
        self.calendar_button.bind(
            "<Leave>", lambda _event: self._set_calendar_hover(False)
        )
        self.calendar_button.bind("<FocusIn>", self._draw_calendar_button)
        self.calendar_button.bind("<FocusOut>", self._draw_calendar_button)
        self._draw_calendar_button()

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(
            fill="both",
            expand=True,
            padx=self._px(22),
            pady=(0, self._px(22)),
        )

        columns_header = tk.Frame(
            list_shell,
            bg=SURFACE,
            height=self._px(30),
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        self._configure_columns(columns_header)
        for column, text in enumerate(("ИГРОК", "ПРИЗ", "ДАТА")):
            tk.Label(
                columns_header,
                text=text,
                bg=SURFACE,
                fg=MUTED,
                anchor="w",
                font=("Segoe UI Semibold", 9),
            ).grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(self._px(16), self._px(6)),
                pady=(self._px(7), self._px(4)),
            )
        tk.Frame(list_shell, bg="#343B36", height=self._px(1)).pack(fill="x")

        body = tk.Frame(list_shell, bg=SURFACE)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            body,
            bg=SURFACE,
            highlightthickness=0,
            borderwidth=0,
        )
        self.scrollbar = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_window = self.canvas.create_window(
            (0, 0),
            window=self.rows_frame,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)

        self.refresh()

    def refresh(self) -> None:
        try:
            self._results = self.app.draw_log_store.load()
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось прочитать журнал розыгрышей:\n{error}",
                parent=self,
            )
            self._results = []

        self._render_results()

    def _on_search_changed(self, *_args: object) -> None:
        self._render_results()

    def _render_results(self) -> None:
        for widget in self.rows_frame.winfo_children():
            widget.destroy()

        terms = self.search_var.get().casefold().split()
        visible_results = [
            (index, result)
            for index, result in enumerate(self._results)
            if self._matches_date_filter(result)
            and (
                not terms
                or all(
                    term in f"{result.winner}\n{result.reward}".casefold()
                    for term in terms
                )
            )
        ]
        total = len(self._results)
        visible_count = len(visible_results)
        date_filter_active = self.date_from is not None or self.date_to is not None
        if terms or date_filter_active:
            self.count_label.configure(text=f"· {visible_count} из {total}")
        else:
            self.count_label.configure(text=f"· {total}" if total else "")

        if not visible_results:
            tk.Label(
                self.rows_frame,
                text=(
                    "Совпадений не найдено"
                    if terms
                    else (
                        "За выбранный период записей нет"
                        if date_filter_active
                        else "История розыгрышей пока пуста"
                    )
                ),
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 11),
                pady=self._px(28),
            ).pack(fill="x")
        for index, result in reversed(visible_results):
            self._add_row(index, result)
        self.canvas.yview_moveto(0.0)
        self._schedule_layout_update()

    def _matches_date_filter(self, result: DrawResult) -> bool:
        if self.date_from is None and self.date_to is None:
            return True
        result_day = draw_result_date(result.timestamp)
        if result_day is None:
            return False
        if self.date_from is not None and result_day < self.date_from:
            return False
        if self.date_to is not None and result_day > self.date_to:
            return False
        return True

    def set_date_filter(
        self,
        start: date | None,
        end: date | None,
    ) -> None:
        if start is not None and end is not None and end < start:
            start, end = end, start
        self.date_from = start
        self.date_to = end
        self._draw_calendar_button()
        self._render_results()

    def _open_date_picker(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> str:
        if self.date_picker is not None and self.date_picker.winfo_exists():
            self.date_picker._close()
            return "break"
        self.date_picker = DateRangePicker(self)
        return "break"

    def _set_calendar_hover(self, hovered: bool) -> None:
        self._calendar_hovered = hovered
        self._draw_calendar_button()

    def _draw_calendar_button(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        button = self.calendar_button
        button.delete("all")
        px = self._px
        width = px(38)
        height = px(34)
        active_filter = self.date_from is not None or self.date_to is not None
        focused = button.focus_get() is button
        hovered = self._calendar_hovered or focused
        border = ACCENT if active_filter else (BORDER_LIGHT if hovered else BORDER)
        icon = ACCENT_HOVER if active_filter else (TEXT if hovered else MUTED)
        button.create_rectangle(
            px(1),
            px(1),
            width - px(1),
            height - px(1),
            fill=SURFACE_LIGHT if hovered or active_filter else SURFACE,
            outline=border,
            width=px(1),
        )
        left, top, right, bottom = px(10), px(9), px(28), px(26)
        button.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=icon,
            width=px(2),
        )
        button.create_line(left, px(14), right, px(14), fill=icon, width=px(2))
        for x in (px(14), px(24)):
            button.create_line(
                x,
                px(6),
                x,
                px(11),
                fill=icon,
                width=px(2),
                capstyle="round",
            )
        for x in (px(15), px(21), px(25)):
            button.create_oval(
                x - px(1),
                px(18),
                x + px(1),
                px(20),
                fill=icon,
                outline=icon,
            )

    def _add_row(self, index: int, result: DrawResult) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(
            row,
            bg=SURFACE,
            padx=self._px(10),
            pady=self._px(8),
        )
        content.pack(fill="x")
        self._configure_columns(content)

        fields: list[tk.Entry] = []
        for column, (value, color, font) in enumerate(
            (
                (result.winner, TEXT, ("Segoe UI", 11)),
                (result.reward, TEXT, ("Segoe UI", 11)),
                (
                    format_draw_timestamp(result.timestamp),
                    MUTED,
                    ("Segoe UI", 10),
                ),
            )
        ):
            field = tk.Entry(
                content,
                bg=SURFACE,
                readonlybackground=SURFACE,
                fg=color,
                insertbackground=TEXT,
                selectbackground=BRAND_GREEN,
                selectforeground=TEXT_BRIGHT,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                font=font,
                state="normal",
                cursor="xterm",
            )
            field.insert(0, value)
            field.configure(state="readonly")
            enable_entry_shortcuts(field)
            field.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(self._px(6), self._px(8)),
            )
            fields.append(field)

        delete = StyledDeleteButton(
            content,
            command=lambda item_index=index: self._delete(item_index),
            background=SURFACE,
        )
        delete.grid(row=0, column=3, padx=(self._px(4), 0))
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(
            fill="x",
            padx=self._px(10),
        )

        def set_hover(hovered: bool) -> None:
            background = ROW_HOVER if hovered else SURFACE
            row.configure(bg=background)
            content.configure(bg=background)
            for field in fields:
                field.configure(readonlybackground=background)
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

        for widget in (row, content, *fields, delete):
            widget.bind(
                "<Enter>",
                lambda _event: set_hover(True),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event: set_hover(False),
                add="+",
            )
            widget.bind("<MouseWheel>", self._scroll)

    def _delete(self, index: int) -> None:
        if not 0 <= index < len(self._results):
            return
        result = self._results[index]
        confirmed = messagebox.askyesno(
            "Удаление записи",
            (
                f"Удалить запись о розыгрыше для игрока «{result.winner}»?\n\n"
                "Запись будет удалена из истории и файла журнала."
            ),
            icon="warning",
            parent=self,
        )
        if not confirmed:
            return
        try:
            self.app.draw_log_store.remove_at(index)
        except (OSError, ValueError, TypeError, IndexError) as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось удалить запись:\n{error}",
                parent=self,
            )
            return
        self.owner.refresh_last_wins()
        self.refresh()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._schedule_layout_update()

    def _resize_rows(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.rows_window, width=event.width)
        self._schedule_layout_update()

    def _schedule_layout_update(self) -> None:
        if self._layout_after_id is None:
            self._layout_after_id = self.after_idle(
                self._run_scheduled_layout_update
            )

    def _run_scheduled_layout_update(self) -> None:
        self._layout_after_id = None
        if self.winfo_exists():
            self._update_scrollbar_visibility()

    def _cancel_layout_update(self) -> None:
        if self._layout_after_id is None:
            return
        try:
            self.after_cancel(self._layout_after_id)
        except tk.TclError:
            pass
        self._layout_after_id = None

    def _schedule_focus_after_date_picker(self) -> None:
        self._cancel_focus_restore()
        self._focus_restore_after_id = self.after_idle(
            self._restore_focus_after_date_picker
        )

    def _restore_focus_after_date_picker(self) -> None:
        self._focus_restore_after_id = None
        try:
            if not self.winfo_exists():
                return
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _cancel_focus_restore(self) -> None:
        if self._focus_restore_after_id is None:
            return
        try:
            self.after_cancel(self._focus_restore_after_id)
        except tk.TclError:
            pass
        self._focus_restore_after_id = None

    def _synchronize_rows_layout(self) -> None:
        """Match the history rows to the final canvas width."""

        self.canvas.itemconfigure(
            self.rows_window,
            width=max(1, self.canvas.winfo_width()),
        )
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _update_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.canvas.winfo_height() + 1
        visibility_changed = False
        if should_show and not self._scrollbar_visible:
            self.scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
            visibility_changed = True
        elif not should_show and self._scrollbar_visible:
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False
            visibility_changed = True
        if visibility_changed:
            self._schedule_layout_update()

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _center_on_application(self) -> None:
        self._center_after_id = None
        self.update_idletasks()
        application = self.owner.winfo_toplevel()
        width = max(self._px(900), self.winfo_width())
        height = max(self._px(580), self.winfo_height())
        x = application.winfo_rootx() + (application.winfo_width() - width) // 2
        y = application.winfo_rooty() + (application.winfo_height() - height) // 2
        self._open_geometry = f"{width}x{height}+{max(0, x)}+{max(0, y)}"

        # On Windows the native frame can be recreated by deiconify() before
        # DWM has restored its dark attributes.  Prepare that first mapped
        # frame off-screen so a default white caption can never be visible.
        if os.name == "nt":
            self.geometry(f"{width}x{height}-32000-32000")
        else:
            self.geometry(self._open_geometry)
        apply_dark_title_bar(self)
        self.deiconify()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.update_idletasks()
        apply_dark_title_bar(self)
        self._open_after_id = self.after(30, self._finish_open)

    def _finish_open(self) -> None:
        self._open_after_id = None
        apply_dark_title_bar(self)
        self.geometry(self._open_geometry)
        self.update_idletasks()
        self._update_scrollbar_visibility()
        self.update_idletasks()
        self._synchronize_rows_layout()
        self.update_idletasks()
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _close(self) -> None:
        self._cancel_open_callbacks()
        self._cancel_layout_update()
        self._cancel_focus_restore()
        if self.date_picker is not None and self.date_picker.winfo_exists():
            self.date_picker._close(restore_focus=False)
        if getattr(self.owner, "history_dialog", None) is self:
            self.owner.history_dialog = None
        self.destroy()

    def _on_destroy(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is self:
            self._cancel_open_callbacks()
            self._cancel_layout_update()
            self._cancel_focus_restore()

    def _cancel_open_callbacks(self) -> None:
        for attribute in ("_center_after_id", "_open_after_id"):
            callback_id = getattr(self, attribute, None)
            if callback_id is None:
                continue
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)
