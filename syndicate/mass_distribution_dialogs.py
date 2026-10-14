"""Settings and saved-report windows for mass distribution."""
from __future__ import annotations

from collections.abc import Callable
import os
import tkinter as tk
from tkinter import messagebox, ttk

from .mass_distribution import ordered_report_events, ordered_report_items
from .models import format_draw_timestamp, nickname_lookup_key
from .platform import apply_dark_title_bar, apply_window_icon, keep_dark_title_bar
from .theme import ACCENT, APP_NAME, BORDER, MUTED, PANEL_BACKGROUND, ROW_HOVER, SURFACE, SURFACE_LIGHT, TEXT
from .widgets import CopyNickname, StyledDeleteButton, styled_button


class _DarkDialogOpenMixin:
    """Prepare native dark dialogs before exposing their first frame."""

    def _prepare_hidden_open(self, parent: tk.Misc, width: int, height: int) -> None:
        self.withdraw()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self._application = parent.winfo_toplevel()
        self._open_size = (width, height)
        self._center_after_id: str | None = None
        self._open_after_id: str | None = None
        self._open_geometry = ""

    def _center_on_application(self) -> None:
        self._center_after_id = None
        self.update_idletasks()
        width = max(self._px(self._open_size[0]), self.winfo_width())
        height = max(self._px(self._open_size[1]), self.winfo_height())
        x = self._application.winfo_rootx() + (self._application.winfo_width() - width) // 2
        y = self._application.winfo_rooty() + (self._application.winfo_height() - height) // 2
        self._open_geometry = f"{width}x{height}+{max(0, x)}+{max(0, y)}"
        self.geometry(f"{width}x{height}-32000-32000" if os.name == "nt" else self._open_geometry)
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
        self._prepare_content_for_show()
        self.update_idletasks()
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _prepare_content_for_show(self) -> None:
        self._update_scroll_region()

    def destroy(self) -> None:
        for attribute in ("_center_after_id", "_open_after_id"):
            job = getattr(self, attribute, None)
            if job is not None:
                self.after_cancel(job)
                setattr(self, attribute, None)
        super().destroy()


class ItemSettingsDialog(_DarkDialogOpenMixin, tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        names: list[str],
        on_save: Callable[[list[str]], None],
        *,
        ui_scale: float,
        get_names: Callable[[], list[str]] | None = None,
        raffle_names: list[str] | None = None,
        on_raffle_save: Callable[[list[str]], None] | None = None,
        get_raffle_names: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui_scale = ui_scale
        self._prepare_hidden_open(parent, 610, 430)
        self._active_tab = "divisible"
        self._item_lists = {"divisible": list(names), "raffle": list(raffle_names or [])}
        self._savers = {"divisible": on_save, "raffle": on_raffle_save}
        self._getters = {"divisible": get_names, "raffle": get_raffle_names}
        self.names = self._item_lists[self._active_tab]
        self.rows: list[dict] = []
        self._scroll_update_after_id: str | None = None
        self._scrollbar_visible = False
        self.title("Настройки предметов")
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(parent.winfo_toplevel())
        self.geometry(f"{round(610 * ui_scale)}x{round(430 * ui_scale)}")
        self.minsize(round(420 * ui_scale), round(300 * ui_scale))
        apply_window_icon(self)
        keep_dark_title_bar(self)
        tabs = tk.Frame(self, bg=PANEL_BACKGROUND)
        tabs.pack(fill="x", padx=self._px(22), pady=(self._px(20), self._px(12)))
        self.tab_buttons: dict[str, tk.Button] = {}
        self._tab_underlines: dict[str, tk.Frame] = {}
        for key, caption in (("divisible", "Делимые"), ("raffle", "Предметы для розыгрыша")):
            tab = tk.Frame(tabs, bg=PANEL_BACKGROUND)
            tab.pack(side="left", padx=(0, self._px(8)))
            button = tk.Button(
                tab, text=caption, command=lambda category=key: self.select_tab(category),
                bg=SURFACE_LIGHT, fg=MUTED, activebackground=SURFACE, activeforeground=TEXT,
                relief="flat", borderwidth=0, cursor="hand2", font=("Segoe UI Semibold", 10),
                padx=self._px(14), pady=self._px(8),
            )
            button.pack(fill="x")
            underline = tk.Frame(tab, bg=PANEL_BACKGROUND, height=self._px(2))
            underline.pack(fill="x")
            self.tab_buttons[key] = button
            self._tab_underlines[key] = underline
        body = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        body.pack(fill="both", expand=True, padx=self._px(22), pady=(0, self._px(20)))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, bg=SURFACE, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._schedule_scroll_update)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)
        self.select_tab("divisible")
        self._center_after_id = self.after_idle(self._center_on_application)

    def _px(self, value: float) -> int:
        return max(1, round(value * self.ui_scale))

    def refresh_items(self) -> None:
        for category, getter in self._getters.items():
            if getter is not None:
                self._item_lists[category] = list(getter())
        self.names = self._item_lists[self._active_tab]
        self._render()

    def select_tab(self, category: str) -> None:
        self._active_tab = category
        for key, button in self.tab_buttons.items():
            active = key == category
            button.configure(bg=SURFACE if active else SURFACE_LIGHT, fg=TEXT if active else MUTED)
            self._tab_underlines[key].configure(bg=ACCENT if active else PANEL_BACKGROUND)
        self.refresh_items()
        self.canvas.yview_moveto(0)

    def _render(self) -> None:
        self.names.sort(key=nickname_lookup_key)
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self.rows = []
        if not self.names:
            tk.Label(
                self.rows_frame, text="Добавьте предметы из списка событий",
                bg=SURFACE, fg=MUTED, font=("Segoe UI", 11), pady=self._px(28),
            ).pack(fill="x")
        for name in self.names:
            self._add_row(name)
        self._schedule_scroll_update()

    def _add_row(self, name: str) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(row, bg=SURFACE, padx=self._px(16), pady=self._px(3))
        content.pack(fill="x")
        delete = StyledDeleteButton(content, command=lambda category=self._active_tab: self._delete(name, category), background=SURFACE)
        delete.pack(side="right", padx=(self._px(12), 0))
        label = tk.Label(content, text=name, bg=SURFACE, fg=TEXT, anchor="w", font=("Segoe UI", 10))
        label.pack(side="left", fill="x", expand=True)
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(fill="x", padx=self._px(10))
        self.rows.append({"name": name, "delete": delete})

        def set_hover(hovered: bool) -> None:
            background = ROW_HOVER if hovered else SURFACE
            for widget in (row, content, label, delete):
                widget.configure(bg=background)
            delete.base_background = background
            delete._redraw()

        for widget in (row, content, label, delete):
            widget.bind("<Enter>", lambda _event: set_hover(True), add="+")
            widget.bind("<Leave>", lambda _event: set_hover(False), add="+")
            widget.bind("<MouseWheel>", self._scroll)

    def _delete(self, name: str, category: str) -> None:
        getter = self._getters[category]
        current_names = getter() if getter is not None else self._item_lists[category]
        names = [value for value in current_names if nickname_lookup_key(value) != nickname_lookup_key(name)]
        try:
            saver = self._savers[category]
            if saver is not None:
                saver(names)
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Не удалось удалить предмет:\n{error}", parent=self)
            return
        self._item_lists[category] = names
        self.refresh_items()

    def _resize_rows(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.rows_window, width=event.width)
        self._schedule_scroll_update()

    def _schedule_scroll_update(self, _event: tk.Event | None = None) -> None:
        if self._scroll_update_after_id is None:
            self._scroll_update_after_id = self.after_idle(self._update_scroll_region)

    def _update_scroll_region(self) -> None:
        self._scroll_update_after_id = None
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        overflow = self.rows_frame.winfo_reqheight() > self.canvas.winfo_height() + 1
        if overflow and not self._scrollbar_visible:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        elif not overflow and self._scrollbar_visible:
            self.scrollbar.grid_remove()
        self._scrollbar_visible = overflow

    def _scroll(self, event: tk.Event) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def destroy(self) -> None:
        if self._scroll_update_after_id is not None:
            self.after_cancel(self._scroll_update_after_id)
            self._scroll_update_after_id = None
        super().destroy()


class DistributionReportDialog(_DarkDialogOpenMixin, tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, reports: list[dict], *, ui_scale: float,
        initial_report: dict | None = None,
        on_load_reports: Callable[[], list[dict]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui_scale = ui_scale
        self._prepare_hidden_open(parent, 1080, 720)
        self.reports = list(reversed(reports))
        self._on_load_reports = on_load_reports
        self.item_rows: list[dict] = []
        self._wrap_labels: list[tuple[tk.Label | CopyNickname, float]] = []
        self._scrollbar_visible = False
        self._scroll_update_after_id: str | None = None
        self._hover_leave_after_id: str | None = None
        self._hovered_row: dict | None = None
        self.current_report: dict | None = None
        self.report_cards: list[dict] = []
        self.event_cards: list[dict] = []
        self._wrap_width: int | None = None
        self._canvas_width: int | None = None
        self._canvas_size: tuple[int, int] | None = None
        self._content_size: tuple[int, int] | None = None
        self._scroll_region = None
        self.title("Отчёт распределения")
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(parent.winfo_toplevel())
        self.geometry(f"{self._px(1080)}x{self._px(720)}")
        self.minsize(self._px(640), self._px(380))
        apply_window_icon(self)
        keep_dark_title_bar(self)
        self.header = tk.Frame(self, bg=PANEL_BACKGROUND)
        self.back_button = styled_button(
            self.header, "К распределениям", self._show_history, SURFACE_LIGHT, TEXT,
        )
        body = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        self.body = body
        body.pack(fill="both", expand=True, padx=self._px(22), pady=(0, self._px(22)))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, bg=SURFACE, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(body, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._resize_rows)
        for surface in (self.canvas, self.rows_frame, body, self.scrollbar):
            surface.bind("<MouseWheel>", self._scroll)
        if initial_report is not None:
            self._show_report(initial_report)
        else:
            self._show_history()
        self._center_after_id = self.after_idle(self._center_on_application)

    def _prepare_content_for_show(self) -> None:
        self._set_wrap_widths(self.canvas.winfo_width())
        self._update_scroll_region()

    def _px(self, value: float) -> int:
        return max(1, round(value * self.ui_scale))

    def _configure_columns(self, frame: tk.Frame) -> None:
        frame.grid_columnconfigure(0, weight=3, uniform="report_columns")
        frame.grid_columnconfigure(1, minsize=self._px(100))
        frame.grid_columnconfigure(2, weight=2, uniform="report_columns")

    def _clear_content(self) -> None:
        self._set_report_hover(None)
        if self._hover_leave_after_id is not None:
            self.after_cancel(self._hover_leave_after_id)
            self._hover_leave_after_id = None
        for widget in self.rows_frame.winfo_children():
            widget.destroy()
        self.item_rows = []
        self._wrap_labels = []
        self._wrap_width = None
        self.report_cards = []
        self.event_cards = []

    def _refresh_content(self, *, reset_scroll: bool = False) -> None:
        self._wrap_width = None
        self._set_wrap_widths(self.canvas.winfo_width())
        self._schedule_scroll_update()
        if reset_scroll:
            self.canvas.yview_moveto(0)

    def _show_history(self) -> None:
        if self._on_load_reports is not None:
            try:
                reports = self._on_load_reports()
            except (OSError, ValueError, TypeError) as error:
                messagebox.showerror(APP_NAME, f"Не удалось открыть отчёты:\n{error}", parent=self)
                return
            self.reports = list(reversed(reports))
        self._clear_content()
        self.current_report = None
        self.title("Отчёты распределений")
        self.header.pack_forget()
        self.body.pack_configure(pady=(self._px(20), self._px(22)))
        self.back_button.pack_forget()
        if self.reports:
            cards_grid = tk.Frame(self.rows_frame, bg=SURFACE)
            cards_grid.pack(fill="x", padx=self._px(7), pady=self._px(7))
            cards_grid.bind("<MouseWheel>", self._scroll)
            for column in range(2):
                cards_grid.grid_columnconfigure(column, weight=1, uniform="distribution_cards")
            for index, report in enumerate(self.reports):
                self._add_report_card(cards_grid, report, index)
        else:
            tk.Label(
                self.rows_frame, text="Распределений пока нет",
                bg=SURFACE, fg=MUTED, font=("Segoe UI", 11), pady=self._px(28),
            ).pack(fill="x")
        self._refresh_content(reset_scroll=True)

    def _add_report_card(self, parent: tk.Frame, report: dict, index: int) -> None:
        section = tk.Frame(
            parent, bg=SURFACE_LIGHT, cursor="hand2", highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=BORDER,
        )
        row, column = divmod(index, 2)
        last_row = (len(self.reports) - 1) // 2
        section.grid(
            row=row, column=column, sticky="nsew",
            padx=(0, self._px(4)) if column == 0 else (self._px(4), 0),
            pady=(0, self._px(7)) if row < last_row else 0,
        )
        participants = {
            nickname_lookup_key(name)
            for event in report["events"] for name in event["participants"]
        }
        item_count = sum(len(event["items"]) for event in report["events"])
        event_count = len(report["events"])
        title = tk.Label(
            section, text=f"Распределение {format_draw_timestamp(report['created_at'])[:5]}",
            bg=SURFACE_LIGHT, fg=TEXT,
            font=("Segoe UI Semibold", 11), anchor="w", cursor="hand2",
        )
        title.pack(fill="x", padx=self._px(16), pady=(self._px(10), 0))
        summary = tk.Label(
            section, text=f"Участников: {len(participants)} · Предметов: {item_count} · Событий: {event_count}",
            bg=SURFACE_LIGHT, fg=MUTED, font=("Segoe UI", 9), anchor="w", cursor="hand2",
        )
        summary.pack(fill="x", padx=self._px(16), pady=(self._px(4), 0))
        date = tk.Label(
            section, text=format_draw_timestamp(report["created_at"]), bg=SURFACE_LIGHT,
            fg=MUTED, font=("Segoe UI", 8), anchor="w", cursor="hand2",
        )
        date.pack(fill="x", padx=self._px(16), pady=(self._px(4), self._px(10)))
        self._wrap_labels.extend([(title, 0.5), (summary, 0.5), (date, 0.5)])
        self.report_cards.append({
            "report": report, "frame": section, "title": title, "summary": summary,
            "date": date, "participant_count": len(participants), "item_count": item_count,
            "event_count": event_count,
        })
        for widget in (section, title, summary, date):
            widget.bind("<Button-1>", lambda _event, data=report: self._show_report(data))
            widget.bind("<MouseWheel>", self._scroll)
            widget.bind("<Enter>", lambda _event, frame=section: frame.configure(highlightbackground=ACCENT))
            widget.bind("<Leave>", lambda _event, frame=section: frame.configure(highlightbackground=BORDER))

    def _show_report(self, report: dict) -> None:
        self._clear_content()
        self.current_report = report
        self.title("Отчёт распределения")
        self.header.pack(
            fill="x", padx=self._px(22), pady=(self._px(20), self._px(12)), before=self.body,
        )
        self.body.pack_configure(pady=(0, self._px(22)))
        self.back_button.pack(side="right", padx=(self._px(8), 0))
        for event in ordered_report_events(report):
            self._add_event(event)
        if self.event_cards:
            self.event_cards[-1]["frame"].pack_configure(pady=self._px(7))
        self._refresh_content(reset_scroll=True)

    def _add_event(self, event: dict) -> None:
        section = tk.Frame(self.rows_frame, bg=SURFACE, highlightthickness=1,
                           highlightbackground=BORDER, highlightcolor=BORDER)
        section.pack(fill="x", padx=self._px(7), pady=(self._px(7), 0))
        section.bind("<MouseWheel>", self._scroll)
        header = tk.Frame(section, bg=SURFACE_LIGHT, cursor="hand2")
        header.pack(fill="x")
        header.grid_columnconfigure(1, weight=1)
        chevron = tk.Label(header, text="▸", bg=SURFACE_LIGHT, fg=ACCENT,
                           font=("Segoe UI Symbol", 12), width=2, cursor="hand2")
        chevron.grid(row=2, column=0, sticky="sw", padx=(self._px(7), 0), pady=(0, self._px(7)))
        title = tk.Label(
            header, text=event["name"], bg=SURFACE_LIGHT, fg=TEXT,
            font=("Segoe UI Semibold", 10), anchor="w", justify="left", cursor="hand2",
        )
        title.grid(row=0, column=1, sticky="ew", pady=(self._px(7), 0), padx=(0, self._px(7)))
        self._wrap_labels.append((title, 1.0))
        date_label = tk.Label(
            header, text=event["timestamp"], bg=SURFACE_LIGHT, fg=MUTED,
            font=("Segoe UI", 8), anchor="w", cursor="hand2",
        )
        date_label.grid(row=1, column=1, sticky="ew", padx=(0, self._px(7)))
        summary = tk.Label(
            header, text=f"Предметов: {len(event['items'])} · Участников: {len(event['participants'])}",
            bg=SURFACE_LIGHT, fg=MUTED, font=("Segoe UI", 8), anchor="w", cursor="hand2",
        )
        summary.grid(row=2, column=1, sticky="ew", pady=(self._px(3), self._px(7)))
        card = {"event": event, "frame": section, "chevron": chevron, "title": title,
                "body": None, "expanded": False, "rows": [], "body_wrap_labels": []}
        self.event_cards.append(card)
        for widget in (header, chevron, title, date_label, summary):
            widget.bind("<Button-1>", lambda _event, data=card: self._toggle_event_card(data))
            widget.bind("<MouseWheel>", self._scroll)

    def _toggle_event_card(self, card: dict) -> None:
        if card["expanded"]:
            self._clear_event_body(card)
        else:
            for other in self.event_cards:
                if other["expanded"]:
                    self._clear_event_body(other)
            self._build_event_body(card)
        self._refresh_content()

    def _clear_event_body(self, card: dict) -> None:
        self._set_report_hover(None)
        if self._hover_leave_after_id is not None:
            self.after_cancel(self._hover_leave_after_id)
            self._hover_leave_after_id = None
        labels = {label for label, _fraction in card["body_wrap_labels"]}
        self._wrap_labels = [(label, fraction) for label, fraction in self._wrap_labels if label not in labels]
        self.item_rows = [row for row in self.item_rows if row["event"] is not card["event"]]
        if card["body"] is not None:
            card["body"].destroy()
        card.update(body=None, expanded=False, rows=[], body_wrap_labels=[])
        card["chevron"].configure(text="▸")
        card["frame"].configure(highlightbackground=BORDER, highlightcolor=BORDER)

    def _build_event_body(self, card: dict) -> None:
        event = card["event"]
        body = tk.Frame(card["frame"], bg=SURFACE)
        card.update(body=body, expanded=True)
        card["chevron"].configure(text="▾")
        card["frame"].configure(highlightbackground=ACCENT, highlightcolor=ACCENT)
        headings = tk.Frame(body, bg=SURFACE, padx=self._px(16))
        headings.pack(fill="x")
        self._configure_columns(headings)
        for column, name in enumerate(("ПРЕДМЕТ", "КОЛ-ВО", "КОМУ ВЫДАТЬ")):
            tk.Label(
                headings, text=name, bg=SURFACE, fg=MUTED,
                font=("Segoe UI Semibold", 9), anchor="center" if column == 1 else "w",
            ).grid(row=0, column=column, sticky="ew", pady=self._px(8))
        tk.Frame(body, bg=BORDER, height=self._px(1)).pack(fill="x")
        row_start = len(self.item_rows)
        wrap_start = len(self._wrap_labels)
        for item in ordered_report_items(event):
            self._add_item(body, event, item, item["allocations"])
        card["rows"] = self.item_rows[row_start:]
        card["body_wrap_labels"] = self._wrap_labels[wrap_start:]
        self._bind_scroll_tree(body)
        body.pack(fill="x")

    def _add_item(self, parent: tk.Frame, event: dict, item: dict, allocations: list[dict]) -> None:
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(row, bg=SURFACE, padx=self._px(16), pady=self._px(7))
        content.pack(fill="x")
        self._configure_columns(content)
        item_cell = tk.Frame(content, bg=SURFACE)
        item_cell.grid(row=0, column=0, rowspan=len(allocations), sticky="nsew")
        name_label = tk.Label(
            item_cell, text=item["name"], bg=SURFACE, fg=TEXT,
            anchor="w", justify="left", font=("Segoe UI Semibold", 10),
        )
        name_label.pack(fill="x", anchor="w")
        self._wrap_labels.append((name_label, 0.6))
        if item["divisible"] and item["quantity"] > 1:
            tk.Label(
                item_cell, text=f"Делится · всего {item['quantity']}", bg=SURFACE,
                fg=MUTED, anchor="w", font=("Segoe UI", 8),
            ).pack(fill="x", pady=(self._px(3), 0))
        recipient_buttons = []
        for index, allocation in enumerate(allocations):
            quantity = tk.Label(
                content, text=str(allocation["quantity"]), bg=SURFACE, fg=ACCENT,
                font=("Segoe UI Semibold", 11),
            )
            quantity.grid(row=index, column=1, sticky="nsew", pady=self._px(2))
            recipient = CopyNickname(content, allocation["participant"], background=SURFACE)
            recipient.grid(row=index, column=2, sticky="w", pady=self._px(2))
            self._wrap_labels.append((recipient, 0.4))
            recipient_buttons.append(recipient)
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(fill="x", padx=self._px(10))
        widgets = list(dict.fromkeys([row, content, item_cell, *item_cell.winfo_children(), *content.winfo_children()]))
        row_data = {"event": event, "item": item, "allocations": allocations,
                    "name_label": name_label, "frame": row, "background_widgets": widgets,
                    "recipient_buttons": recipient_buttons}
        self.item_rows.append(row_data)
        for widget in widgets:
            if isinstance(widget, CopyNickname):
                for sequence in ("<Enter>", "<Motion>"):
                    widget.bind(sequence, lambda _event, chip=widget, data=row_data:
                                self._enter_report_row(None if chip._hovered else data), add="+")
            else:
                widget.bind("<Enter>", lambda _event, data=row_data: self._enter_report_row(data), add="+")
            widget.bind("<Leave>", self._schedule_hover_leave, add="+")

    def _enter_report_row(self, row_data: dict | None) -> None:
        if self._hover_leave_after_id is not None:
            self.after_cancel(self._hover_leave_after_id)
            self._hover_leave_after_id = None
        self._set_report_hover(row_data)

    def _set_report_hover(self, row_data: dict | None) -> None:
        if self._hovered_row is row_data:
            return
        for data, background in ((self._hovered_row, SURFACE), (row_data, ROW_HOVER)):
            if data is not None:
                for widget in data["background_widgets"]:
                    widget.configure(bg=background)
        self._hovered_row = row_data

    def _schedule_hover_leave(self, _event: tk.Event) -> None:
        if self._hover_leave_after_id is None:
            self._hover_leave_after_id = self.after_idle(self._finish_hover_leave)

    def _finish_hover_leave(self) -> None:
        self._hover_leave_after_id = None
        if self._hovered_row is None:
            return
        try:
            pointed = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
        except (KeyError, tk.TclError):
            pointed = None
        while pointed is not None:
            if pointed is self._hovered_row["frame"]:
                return
            pointed = getattr(pointed, "master", None)
        self._set_report_hover(None)

    def _set_wrap_widths(self, width: int) -> None:
        if self._wrap_width == width:
            return
        self._wrap_width = width
        available = max(self._px(240), width - self._px(140))
        for label, fraction in self._wrap_labels:
            wrap_width = max(self._px(80), round(available * fraction) - self._px(12))
            if isinstance(label, CopyNickname):
                label.set_max_width(wrap_width)
            else:
                label.configure(wraplength=wrap_width)

    def _resize_rows(self, event: tk.Event) -> None:
        size = (event.width, event.height)
        if self._canvas_size == size:
            return
        self._canvas_size = size
        if self._canvas_width != event.width:
            self._canvas_width = event.width
            self.canvas.itemconfigure(self.rows_window, width=event.width)
            self._set_wrap_widths(event.width)
        self._schedule_scroll_update()

    def _on_content_configure(self, event: tk.Event) -> None:
        size = (event.width, event.height)
        if self._content_size != size:
            self._content_size = size
            self._schedule_scroll_update()

    def _schedule_scroll_update(self, _event: tk.Event | None = None) -> None:
        if self._scroll_update_after_id is None:
            self._scroll_update_after_id = self.after_idle(self._update_scroll_region)

    def _update_scroll_region(self) -> None:
        self._scroll_update_after_id = None
        region = self.canvas.bbox("all")
        if region != self._scroll_region:
            self._scroll_region = region
            self.canvas.configure(scrollregion=region)
        overflow = self.rows_frame.winfo_reqheight() > self.canvas.winfo_height() + 1
        if overflow and not self._scrollbar_visible:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        elif not overflow and self._scrollbar_visible:
            self.scrollbar.grid_remove()
        self._scrollbar_visible = overflow

    def _scroll(self, event: tk.Event) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll((-1 if event.delta > 0 else 1) * 3, "units")
        return "break"

    def _bind_scroll_tree(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._scroll)
        for child in widget.winfo_children():
            self._bind_scroll_tree(child)

    def destroy(self) -> None:
        for attribute in ("_center_after_id", "_open_after_id", "_hover_leave_after_id"):
            job = getattr(self, attribute, None)
            if job is not None:
                self.after_cancel(job)
                setattr(self, attribute, None)
        if self._scroll_update_after_id is not None:
            self.after_cancel(self._scroll_update_after_id)
            self._scroll_update_after_id = None
        super().destroy()
