"""Event and reward selection for the mass-distribution mode."""
from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox, ttk

from .mass_distribution import DistributionEvent, DistributionItem, DistributionRequest, event_identity
from .mass_distribution_dialogs import ItemSettingsDialog, DistributionReportDialog
from .models import nickname_lookup_key

from .theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_NAME,
    BACKGROUND,
    BORDER,
    CTA_BACKGROUND,
    CTA_BORDER,
    CTA_DISABLED,
    DANGER,
    DISABLED_TEXT,
    MUTED,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
)
from .widgets import StyledCheckbutton, primary_action_button, styled_button


class DistributionParseError(ValueError):
    """Raised when pasted distribution data contains an invalid row."""


def parse_distribution_events(text: str) -> list[DistributionEvent]:
    """Parse tab-separated reward rows and group them by event and date."""

    grouped: dict[tuple[str, str], list[DistributionItem]] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        columns = [value.strip() for value in raw_line.split("\t")]
        if len(columns) != 4:
            raise DistributionParseError(
                f"Строка {line_number}: ожидаются 4 столбца, разделённые табуляцией."
            )
        item_name, quantity_text, event_name, timestamp = columns
        if not item_name or not event_name or not timestamp:
            raise DistributionParseError(
                f"Строка {line_number}: название предмета, событие и дата обязательны."
            )
        try:
            quantity = int(quantity_text)
        except ValueError as error:
            raise DistributionParseError(
                f"Строка {line_number}: количество должно быть целым числом."
            ) from error
        if quantity < 1:
            raise DistributionParseError(
                f"Строка {line_number}: количество должно быть больше нуля."
            )
        key = (event_name, timestamp)
        grouped.setdefault(key, []).append(DistributionItem(item_name, quantity))

    return [
        DistributionEvent(event_name, timestamp, tuple(items))
        for (event_name, timestamp), items in grouped.items()
    ]


class MassDistributionPanel(tk.Frame):
    """Independent workspace shown in place of the wheel."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        ui_scale: float,
        on_event_selected: Callable[[tuple[str, str] | None], None] | None = None,
        on_paste_participants: Callable[[tuple[str, str], str], list[str]] | None = None,
        on_distribute: Callable[[list[DistributionRequest]], dict] | None = None,
        on_divisible_items_changed: Callable[[list[str]], None] | None = None,
        on_raffle_items_changed: Callable[[list[str]], None] | None = None,
        on_load_reports: Callable[[], list[dict]] | None = None,
        divisible_items: list[str] | None = None,
        raffle_items: list[str] | None = None,
    ) -> None:
        super().__init__(parent, bg=BACKGROUND)
        self.ui_scale = ui_scale
        self.events: list[DistributionEvent] = []
        self.event_cards: list[dict[str, object]] = []
        self._event_cards_by_key: dict[tuple[str, str], dict[str, object]] = {}
        self._on_event_selected = on_event_selected
        self._on_paste_participants = on_paste_participants
        self._on_distribute = on_distribute
        self._on_divisible_items_changed = on_divisible_items_changed
        self._on_raffle_items_changed = on_raffle_items_changed
        self._on_load_reports = on_load_reports
        self.divisible_items = list(divisible_items or [])
        self.raffle_items = list(raffle_items or [])
        self._raffle_item_keys = {nickname_lookup_key(name) for name in self.raffle_items}
        self._distributed_event_keys: set[tuple[str, str]] = set()
        self._completed_events: dict[tuple[str, str], dict] = {}
        self._active_event_key: tuple[str, str] | None = None
        self._scroll_update_after_id: str | None = None
        self._scroll_region = None
        self._canvas_width: int | None = None
        self._build_ui()

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _build_ui(self) -> None:
        heading = tk.Frame(self, bg=BACKGROUND, height=self._px(64))
        heading.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(18), 0),
        )
        heading.pack_propagate(False)

        tk.Label(
            heading,
            text=APP_NAME,
            bg=BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 21),
        ).pack(side="left", anchor="w")
        self.paste_button = styled_button(
            heading,
            "Из буфера",
            self._paste_events,
            SURFACE_LIGHT,
            TEXT,
        )
        self.paste_button.pack(side="right")
        self.clear_button = styled_button(
            heading,
            "Очистить",
            self.clear,
            SURFACE_LIGHT,
            MUTED,
        )
        self.clear_button.configure(state="disabled")
        self.clear_button.pack(side="right", padx=(0, self._px(8)))
        workspace = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        workspace.pack(
            fill="both",
            expand=True,
            padx=self._px(22),
            pady=(0, self._px(12)),
        )

        toolbar = tk.Frame(workspace, bg=SURFACE)
        toolbar.pack(
            fill="x",
            padx=self._px(12),
            pady=(self._px(11), self._px(8)),
        )
        tk.Label(
            toolbar,
            text="СОБЫТИЯ",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 12),
        ).pack(side="left")
        self.count_label = tk.Label(
            toolbar,
            text="· 0",
            bg=SURFACE,
            fg=ACCENT,
            font=("Segoe UI Semibold", 11),
        )
        self.count_label.pack(side="left", padx=(self._px(6), 0))

        list_body = tk.Frame(
            workspace,
            bg=SURFACE,
        )
        list_body.pack(
            fill="both",
            expand=True,
            padx=self._px(12),
            pady=(0, self._px(16)),
        )
        list_body.grid_rowconfigure(0, weight=1)
        list_body.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            list_body,
            bg=SURFACE,
            highlightthickness=0,
            borderwidth=0,
        )
        self.scrollbar = ttk.Scrollbar(
            list_body,
            orient="vertical",
            command=self.canvas.yview,
        )
        self._scrollbar_visible = False
        self.events_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.events_window = self.canvas.create_window(
            (0, 0),
            window=self.events_frame,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.events_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_events)
        for surface in (self.canvas, self.events_frame, list_body, workspace, self.scrollbar):
            surface.bind("<MouseWheel>", self._scroll)
        self._render_events()

        actions = tk.Frame(self, bg=BACKGROUND)
        actions.pack(fill="x", padx=self._px(22), pady=(0, self._px(24)))
        buttons = tk.Frame(actions, bg=BACKGROUND)
        buttons.pack(fill="x")
        self.distribute_button = primary_action_button(buttons, "РАСПРЕДЕЛИТЬ", self._distribute)
        self.distribute_button.pack(fill="x")
        self._refresh_distribute_button()

    def _refresh_distribute_button(self) -> None:
        if not hasattr(self, "distribute_button"):
            return
        enabled = any(
            card["event"].key not in self._distributed_event_keys
            and card["enabled_var"].get()
            and any(item["enabled_var"].get() for item in card["items"])
            for card in self.event_cards
        )
        border = CTA_BORDER if enabled else CTA_DISABLED
        self.distribute_button.configure(
            state="normal" if enabled else "disabled",
            bg=CTA_BACKGROUND if enabled else CTA_DISABLED,
            highlightbackground=border, highlightcolor=border,
        )

    def _load_completed_events(self) -> None:
        if self._on_load_reports is None:
            return
        try:
            reports = self._on_load_reports()
        except (OSError, ValueError, TypeError):
            # The distribute/report actions show the error. Never overwrite history.
            return
        self._completed_events = {
            event_identity(DistributionEvent(event["name"], event["timestamp"], ())): event
            for report in reports for event in report["events"]
        }
        for event in self.events:
            try:
                if event_identity(event) in self._completed_events:
                    self._distributed_event_keys.add(event.key)
            except ValueError:
                continue

    def _distribution_requests(self) -> list[DistributionRequest]:
        requests = []
        for card in self.event_cards:
            event = card["event"]
            if not card["enabled_var"].get() or event.key in self._distributed_event_keys:
                continue
            items = tuple(row["item"] for row in card["items"]
                          if row["enabled_var"].get() and not self._is_raffle_item(row["item"].name))
            if items:
                requests.append(DistributionRequest(
                    DistributionEvent(event.name, event.timestamp, items),
                    tuple(card["participant_names"]),
                ))
        return requests

    def _distribute(self) -> None:
        if self._on_distribute is None:
            return
        try:
            requests = self._distribution_requests()
            report = self._on_distribute(requests)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(APP_NAME, str(error), parent=self)
            return
        self._distributed_event_keys.update(request.event.key for request in requests)
        for event in report["events"]:
            self._completed_events[event_identity(DistributionEvent(event["name"], event["timestamp"], ()))] = event
        self.clear()
        DistributionReportDialog(
            self, [report], ui_scale=self.ui_scale, initial_report=report,
            on_load_reports=self._on_load_reports,
        )

    def _mark_completed_card(self, card: dict[str, object]) -> None:
        card["title_label"].configure(text=f"{card['event'].name} · распределено")
        card["enabled_var"].set(False)
        card["checkbox"].configure(state="disabled")
        for row in card["items"]:
            row["checkbox"].configure(state="disabled")
        try:
            saved_event = self._completed_events.get(event_identity(card["event"]))
        except ValueError:
            saved_event = None
        if saved_event is not None:
            card["participant_names"] = list(saved_event["participants"])
            self._refresh_participant_summary(card)

    def _open_reports(self) -> None:
        if self._on_load_reports is None:
            return
        try:
            reports = self._on_load_reports()
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(APP_NAME, f"Не удалось открыть отчёты:\n{error}", parent=self)
            return
        DistributionReportDialog(self, reports, ui_scale=self.ui_scale)

    def _open_item_settings(self) -> None:
        dialog = getattr(self, "_item_settings_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh_items()
            dialog.lift()
            return
        self._item_settings_dialog = ItemSettingsDialog(
            self, self.divisible_items, self._set_divisible_items, ui_scale=self.ui_scale,
            get_names=lambda: list(self.divisible_items),
            raffle_names=self.raffle_items, on_raffle_save=self._set_raffle_items,
            get_raffle_names=lambda: list(self.raffle_items),
        )

    def _set_divisible_items(self, names: list[str]) -> None:
        if self._on_divisible_items_changed is not None:
            self._on_divisible_items_changed(names)
        self.divisible_items = list(names)
        dialog = getattr(self, "_item_settings_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh_items()
        for card in self.event_cards:
            for row in card["items"]:
                self._refresh_item_state(card, row)

    def _toggle_divisible_item(self, item_name: str) -> None:
        key = nickname_lookup_key(item_name)
        names = [name for name in self.divisible_items if nickname_lookup_key(name) != key]
        if len(names) == len(self.divisible_items):
            names.append(item_name)
        try:
            self._set_divisible_items(names)
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Не удалось сохранить делимые предметы:\n{error}", parent=self)

    def _set_raffle_items(self, names: list[str]) -> None:
        if self._on_raffle_items_changed is not None:
            self._on_raffle_items_changed(names)
        added_keys = {nickname_lookup_key(name) for name in names} - {
            nickname_lookup_key(name) for name in self.raffle_items
        }
        self.raffle_items = list(names)
        self._raffle_item_keys = {nickname_lookup_key(name) for name in self.raffle_items}
        dialog = getattr(self, "_item_settings_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh_items()
        for card in self.event_cards:
            for row in card["items"]:
                if nickname_lookup_key(row["item"].name) in added_keys:
                    row["enabled_var"].set(False)
                self._refresh_item_state(card, row)

    def _toggle_raffle_item(self, item_name: str) -> None:
        key = nickname_lookup_key(item_name)
        names = [name for name in self.raffle_items if nickname_lookup_key(name) != key]
        if len(names) == len(self.raffle_items):
            names.append(item_name)
        try:
            self._set_raffle_items(names)
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Не удалось сохранить предметы для розыгрыша:\n{error}", parent=self)

    def _paste_events(self) -> None:
        try:
            clipboard_text = str(self.clipboard_get())
        except tk.TclError:
            clipboard_text = ""
        if not clipboard_text.strip():
            messagebox.showwarning(
                APP_NAME,
                "В буфере обмена нет текста со списком предметов.",
                parent=self,
            )
            return
        try:
            events = parse_distribution_events(clipboard_text)
        except DistributionParseError as error:
            if "ожидаются 4 столбца" in str(error):
                messagebox.showwarning(
                    APP_NAME,
                    "В буфере не найдено событий.",
                    parent=self,
                )
                return
            messagebox.showerror(APP_NAME, str(error), parent=self)
            return
        if not events:
            messagebox.showwarning(
                APP_NAME,
                "В буфере не найдено событий.",
                parent=self,
            )
            return
        self.set_events(events)

    def set_events(self, events: list[DistributionEvent]) -> None:
        self._set_active_event(None)
        self.events = list(events)
        self._load_completed_events()
        self._render_events()

    def clear(self) -> None:
        self._set_active_event(None)
        self.events = []
        self._render_events()

    def snapshot(self) -> list[dict]:
        """Keep the draft intact when the app rebuilds its UI for another monitor."""
        return [
            {
                "event": card["event"],
                "enabled": card["enabled_var"].get(),
                "items_enabled": [row["enabled_var"].get() for row in card["items"]],
                "participants": list(card["participant_names"]),
                "expanded": card["expanded"],
            }
            for card in self.event_cards
        ]

    def restore_snapshot(self, snapshot: list[dict]) -> None:
        self.set_events([entry["event"] for entry in snapshot])
        for card, entry in zip(self.event_cards, snapshot):
            if card["event"].key not in self._distributed_event_keys:
                card["enabled_var"].set(entry["enabled"])
                for row, enabled in zip(card["items"], entry["items_enabled"]):
                    row["enabled_var"].set(enabled)
                self.set_event_participants(card["event"].key, entry["participants"])
            if entry["expanded"]:
                self._toggle_event(card)

    def selected_items(self) -> list[tuple[DistributionEvent, DistributionItem]]:
        """Return items enabled both individually and by their event."""

        selected: list[tuple[DistributionEvent, DistributionItem]] = []
        for card in self.event_cards:
            event = card.get("event")
            event_enabled = card.get("enabled_var")
            item_rows = card.get("items")
            if (
                not isinstance(event, DistributionEvent)
                or not isinstance(event_enabled, tk.BooleanVar)
                or not event_enabled.get()
                or not isinstance(item_rows, list)
            ):
                continue
            for item_row in item_rows:
                if not isinstance(item_row, dict):
                    continue
                item = item_row.get("item")
                enabled_var = item_row.get("enabled_var")
                if (
                    isinstance(item, DistributionItem)
                    and isinstance(enabled_var, tk.BooleanVar)
                    and enabled_var.get()
                    and not self._is_raffle_item(item.name)
                ):
                    selected.append((event, item))
        return selected

    def _render_events(self) -> None:
        for card in self.event_cards:
            job = card.get("copied_label_after_id")
            if isinstance(job, str):
                self.after_cancel(job)
        for child in self.events_frame.winfo_children():
            child.destroy()
        self.event_cards = []
        self._event_cards_by_key = {}
        item_count = sum(len(event.items) for event in self.events)
        self.count_label.configure(
            text=f"· {len(self.events)} / {item_count} предметов"
        )
        self.clear_button.configure(
            state="normal" if item_count else "disabled"
        )
        self._refresh_distribute_button()

        if not self.events:
            empty = tk.Frame(self.events_frame, bg=SURFACE)
            empty.pack(fill="both", expand=True, pady=self._px(110))
            tk.Label(
                empty,
                text="Список событий пуст",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 11),
            ).pack()
            tk.Label(
                empty,
                text="Скопируйте таблицу и нажмите «Из буфера»",
                bg=SURFACE,
                fg=DISABLED_TEXT,
                font=("Segoe UI", 9),
            ).pack(pady=(self._px(5), 0))
            self._bind_mousewheel_tree(empty)
            self._schedule_scroll_update()
            return

        for event in self.events:
            self._create_event_card(event)
        self._refresh_distribute_button()
        self._schedule_scroll_update()

    def _create_event_card(self, event: DistributionEvent) -> None:
        card_frame = tk.Frame(
            self.events_frame,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        card_frame.pack(
            fill="x",
            padx=self._px(7),
            pady=(self._px(7), 0),
        )
        header = tk.Frame(card_frame, bg=SURFACE_LIGHT, cursor="hand2")
        header.pack(fill="x")
        header.grid_columnconfigure(1, weight=1)

        chevron = tk.Label(
            header,
            text="▸",
            bg=SURFACE_LIGHT,
            fg=ACCENT,
            font=("Segoe UI Symbol", 12),
            width=2,
            cursor="hand2",
        )
        chevron.grid(
            row=2,
            column=0,
            sticky="sw",
            padx=(self._px(7), 0),
            pady=(0, self._px(7)),
        )
        title_label = tk.Label(
            header,
            text=f"{event.name} · распределено" if event.key in self._distributed_event_keys else event.name,
            bg=SURFACE_LIGHT,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
            anchor="w",
            cursor="hand2",
        )
        title_label.grid(row=0, column=1, sticky="ew", pady=(self._px(7), 0))
        date_label = tk.Label(
            header,
            text=event.timestamp,
            bg=SURFACE_LIGHT,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            cursor="hand2",
        )
        date_label.grid(row=1, column=1, sticky="ew", pady=(0, self._px(7)))
        participants_label = tk.Label(
            header,
            text="необходимо выбрать участников",
            bg=SURFACE_LIGHT,
            fg=DANGER,
            font=("Segoe UI Semibold", 8),
            anchor="w",
            justify="left",
            wraplength=self._px(560),
            cursor="hand2",
        )
        participants_label.grid(
            row=2,
            column=1,
            sticky="ew",
            pady=(0, self._px(7)),
        )
        copied_label = tk.Label(
            header,
            text="Скопировано",
            bg=SURFACE_LIGHT,
            fg=ACCENT,
            font=("Segoe UI Semibold", 8),
        )
        enabled_var = tk.BooleanVar(value=True)
        checkbox = StyledCheckbutton(
            header,
            variable=enabled_var,
            background=SURFACE_LIGHT,
        )
        checkbox.grid(
            row=0,
            column=2,
            rowspan=2,
            padx=(self._px(8), self._px(7)),
        )
        participant_clipboard_icon = tk.Label(
            header,
            text="⧉",
            bg=SURFACE_LIGHT,
            fg=MUTED,
            font=("Segoe UI Symbol", 11),
            cursor="hand2",
        )
        participant_clipboard_icon.grid(
            row=2,
            column=2,
            sticky="n",
            padx=(self._px(8), self._px(7)),
            pady=(0, self._px(5)),
        )

        body = tk.Frame(card_frame, bg=SURFACE)
        card: dict[str, object] = {
            "event": event,
            "frame": card_frame,
            "header": header,
            "body": body,
            "chevron": chevron,
            "title_label": title_label,
            "date_label": date_label,
            "participants_label": participants_label,
            "copied_label": copied_label,
            "copied_label_after_id": None,
            "participant_names": [],
            "checkbox": checkbox,
            "participant_clipboard_icon": participant_clipboard_icon,
            "enabled_var": enabled_var,
            "expanded": False,
            "items": [],
            "selection_syncing": False,
        }
        self.event_cards.append(card)
        self._event_cards_by_key[event.key] = card

        for widget in (
            header,
            chevron,
            title_label,
            date_label,
            participants_label,
        ):
            widget.bind(
                "<Button-1>",
                lambda _event, data=card: self._toggle_event(data),
            )
        enabled_var.trace_add(
            "write",
            lambda *_args, data=card: self._on_event_selection_changed(data),
        )
        participant_clipboard_icon.bind(
            "<Button-1>",
            lambda _event, data=card: self._use_participant_clipboard(data),
        )
        participant_clipboard_icon.bind(
            "<Enter>",
            lambda _event, icon=participant_clipboard_icon: icon.configure(
                fg=ACCENT_HOVER
            ),
        )
        participant_clipboard_icon.bind(
            "<Leave>",
            lambda _event, data=card: self._refresh_participant_clipboard_icon(data),
        )

        item_rows = card["items"]
        assert isinstance(item_rows, list)
        for index, item in enumerate(event.items):
            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill="x")
            if index:
                tk.Frame(row, bg="#343B36", height=self._px(1)).pack(fill="x")
            content = tk.Frame(row, bg=SURFACE)
            content.pack(fill="x", padx=self._px(10), pady=self._px(3))
            item_enabled = tk.BooleanVar(value=not self._is_raffle_item(item.name))
            item_checkbox = StyledCheckbutton(
                content,
                variable=item_enabled,
                background=SURFACE,
            )
            item_checkbox.pack(side="right", padx=(self._px(8), 0))
            raffle_button = styled_button(
                content, "В розыгрыш", lambda name=item.name: self._toggle_raffle_item(name),
                SURFACE_LIGHT, MUTED,
            )
            raffle_button.configure(font=("Segoe UI Semibold", 8), padx=self._px(5), pady=self._px(2), width=13)
            raffle_button.pack(side="right", padx=(self._px(8), 0))
            split_button = None
            if item.quantity > 1:
                split_button = styled_button(
                    content,
                    "Делить",
                    lambda name=item.name: self._toggle_divisible_item(name),
                    SURFACE_LIGHT,
                    MUTED,
                )
                split_button.configure(font=("Segoe UI Semibold", 8), padx=self._px(5), pady=self._px(2), width=8)
                split_button.pack(side="right", padx=(self._px(8), 0))
            quantity_label = tk.Label(
                content,
                text=f"× {item.quantity}",
                bg=SURFACE,
                fg=ACCENT_HOVER,
                font=("Segoe UI Semibold", 9),
                width=7,
                anchor="e",
            )
            quantity_label.pack(side="right")
            name_label = tk.Label(
                content,
                text=item.name,
                bg=SURFACE,
                fg=TEXT,
                font=("Segoe UI", 9),
                anchor="w",
            )
            name_label.pack(side="left", fill="x", expand=True)
            item_data: dict[str, object] = {
                "item": item,
                "row": row,
                "content": content,
                "name_label": name_label,
                "quantity_label": quantity_label,
                "checkbox": item_checkbox,
                "split_button": split_button,
                "raffle_button": raffle_button,
                "enabled_var": item_enabled,
            }
            item_rows.append(item_data)
            item_enabled.trace_add(
                "write",
                lambda *_args, event_card=card, data=item_data: (
                    self._on_item_selection_changed(event_card, data)
                ),
            )

        card["selection_syncing"] = True
        enabled_var.set(any(row["enabled_var"].get() for row in item_rows))
        card["selection_syncing"] = False
        self._refresh_event_state(card)
        if event.key in self._distributed_event_keys:
            self._mark_completed_card(card)
        self._bind_mousewheel_tree(card_frame)

    def _toggle_event(self, card: dict[str, object]) -> None:
        body = card.get("body")
        chevron = card.get("chevron")
        frame = card.get("frame")
        event = card.get("event")
        if not (
            isinstance(body, tk.Frame)
            and isinstance(chevron, tk.Label)
            and isinstance(frame, tk.Frame)
            and isinstance(event, DistributionEvent)
        ):
            return
        expanded = not bool(card.get("expanded"))
        if expanded:
            for other_card in self.event_cards:
                if other_card is card or not other_card.get("expanded"):
                    continue
                other_card["expanded"] = False
                other_body = other_card.get("body")
                other_chevron = other_card.get("chevron")
                other_frame = other_card.get("frame")
                if isinstance(other_body, tk.Frame):
                    other_body.pack_forget()
                if isinstance(other_chevron, tk.Label):
                    other_chevron.configure(text="▸")
                if isinstance(other_frame, tk.Frame):
                    other_frame.configure(
                        highlightbackground=BORDER,
                        highlightcolor=BORDER,
                    )
            card["expanded"] = True
            body.pack(fill="x")
            chevron.configure(text="▾")
            frame.configure(
                highlightbackground=ACCENT,
                highlightcolor=ACCENT,
            )
            self._set_active_event(
                None if event.key in self._distributed_event_keys else event.key
            )
        else:
            card["expanded"] = False
            body.pack_forget()
            chevron.configure(text="▸")
            frame.configure(
                highlightbackground=BORDER,
                highlightcolor=BORDER,
            )
            self._set_active_event(None)
        self._schedule_scroll_update()

    def _set_active_event(self, event_key: tuple[str, str] | None) -> None:
        if self._active_event_key == event_key:
            return
        self._active_event_key = event_key
        if self._on_event_selected is not None:
            self._on_event_selected(event_key)

    def set_event_participants(
        self,
        event_key: tuple[str, str],
        participant_names: list[str],
    ) -> None:
        card = self._event_cards_by_key.get(event_key)
        if card is None:
            return
        card["participant_names"] = list(participant_names)
        self._refresh_participant_summary(card)
        self._schedule_scroll_update()

    def _use_participant_clipboard(self, card: dict[str, object]) -> str:
        """Copy an event roster, or use clipboard text to populate an empty one."""

        event = card.get("event")
        names = card.get("participant_names")
        if not isinstance(event, DistributionEvent) or not isinstance(names, list):
            return "break"
        if names:
            self.clipboard_clear()
            self.clipboard_append(", ".join(str(name) for name in names))
            self._show_copied_feedback(card)
            return "break"
        try:
            clipboard_text = str(self.clipboard_get())
        except tk.TclError:
            clipboard_text = ""
        if not clipboard_text.strip():
            messagebox.showwarning(
                APP_NAME,
                "В буфере обмена нет списка участников.",
                parent=self,
            )
            return "break"
        if self._on_paste_participants is not None:
            participant_names = self._on_paste_participants(event.key, clipboard_text)
            self.set_event_participants(event.key, participant_names)
        return "break"

    def _refresh_participant_summary(self, card: dict[str, object]) -> None:
        label = card.get("participants_label")
        names = card.get("participant_names")
        enabled_var = card.get("enabled_var")
        if not isinstance(label, tk.Label) or not isinstance(names, list):
            return
        if names:
            event_enabled = (
                enabled_var.get()
                if isinstance(enabled_var, tk.BooleanVar)
                else True
            )
            label.configure(
                text=", ".join(str(name) for name in names),
                fg=MUTED if event_enabled else DISABLED_TEXT,
            )
        else:
            label.configure(
                text="необходимо выбрать участников",
                fg=DANGER,
            )
        self._refresh_participant_clipboard_icon(card)

    def _refresh_participant_clipboard_icon(self, card: dict[str, object]) -> None:
        icon = card.get("participant_clipboard_icon")
        if isinstance(icon, tk.Label):
            icon.configure(fg=MUTED)

    def _show_copied_feedback(self, card: dict[str, object]) -> None:
        label = card.get("copied_label")
        icon = card.get("participant_clipboard_icon")
        header = card.get("header")
        if not (
            isinstance(label, tk.Label)
            and isinstance(icon, tk.Label)
            and isinstance(header, tk.Frame)
        ):
            return
        job = card.get("copied_label_after_id")
        if isinstance(job, str):
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        header.update_idletasks()
        label.place(
            in_=header,
            x=icon.winfo_x() - self._px(1),
            y=icon.winfo_y() + icon.winfo_height() // 2,
            anchor="e",
        )
        label.configure(fg=ACCENT)
        self._fade_copied_feedback(card, 0)

    def _fade_copied_feedback(self, card: dict[str, object], step: int) -> None:
        label = card.get("copied_label")
        if not isinstance(label, tk.Label) or not label.winfo_exists():
            return
        total_steps = 18
        amount = step / total_steps
        label.configure(fg=self._blend_color(ACCENT, SURFACE_LIGHT, amount))
        if step >= total_steps:
            label.place_forget()
            card["copied_label_after_id"] = None
            return
        card["copied_label_after_id"] = self.after(
            65,
            lambda: self._fade_copied_feedback(card, step + 1),
        )

    @staticmethod
    def _blend_color(start: str, end: str, amount: float) -> str:
        start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
        end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
        return "#" + "".join(
            f"{round(left + (right - left) * amount):02X}"
            for left, right in zip(start_rgb, end_rgb)
        )

    def _is_raffle_item(self, name: str) -> bool:
        return nickname_lookup_key(name) in self._raffle_item_keys

    def _on_event_selection_changed(self, card: dict[str, object]) -> None:
        if card["selection_syncing"]:
            return
        card["selection_syncing"] = True
        try:
            enabled = card["enabled_var"].get() and card["event"].key not in self._distributed_event_keys
            for row in card["items"]:
                selected = enabled and not self._is_raffle_item(row["item"].name)
                if row["enabled_var"].get() != selected:
                    row["enabled_var"].set(selected)
            actual = any(row["enabled_var"].get() for row in card["items"])
            if card["enabled_var"].get() != actual:
                card["enabled_var"].set(actual)
        finally:
            card["selection_syncing"] = False
        self._refresh_event_state(card)

    def _on_item_selection_changed(self, card: dict[str, object], row: dict[str, object]) -> None:
        if card["selection_syncing"]:
            return
        before = card["enabled_var"].get()
        card["selection_syncing"] = True
        try:
            if (self._is_raffle_item(row["item"].name)
                    or card["event"].key in self._distributed_event_keys):
                if row["enabled_var"].get():
                    row["enabled_var"].set(False)
            actual = any(item["enabled_var"].get() for item in card["items"])
            if before != actual:
                card["enabled_var"].set(actual)
        finally:
            card["selection_syncing"] = False
        if before != actual:
            self._refresh_event_state(card)
        else:
            self._refresh_item_state(card, row)

    def _refresh_event_state(self, card: dict[str, object]) -> None:
        enabled_var = card.get("enabled_var")
        title_label = card.get("title_label")
        date_label = card.get("date_label")
        participants_label = card.get("participants_label")
        item_rows = card.get("items")
        if not isinstance(enabled_var, tk.BooleanVar):
            return
        enabled = enabled_var.get()
        if isinstance(title_label, tk.Label):
            title_label.configure(fg=TEXT if enabled else DISABLED_TEXT)
        if isinstance(date_label, tk.Label):
            date_label.configure(fg=MUTED if enabled else DISABLED_TEXT)
        if isinstance(participants_label, tk.Label):
            self._refresh_participant_summary(card)
        if isinstance(item_rows, list):
            for item_row in item_rows:
                if isinstance(item_row, dict):
                    self._refresh_item_state(card, item_row)
        self._refresh_distribute_button()

    def _refresh_item_state(
        self,
        card: dict[str, object],
        item_row: dict[str, object],
    ) -> None:
        event_enabled = card.get("enabled_var")
        item_enabled = item_row.get("enabled_var")
        name_label = item_row.get("name_label")
        quantity_label = item_row.get("quantity_label")
        if not (
            isinstance(event_enabled, tk.BooleanVar)
            and isinstance(item_enabled, tk.BooleanVar)
        ):
            return
        item = item_row.get("item")
        raffle = isinstance(item, DistributionItem) and self._is_raffle_item(item.name)
        check = item_row.get("checkbox")
        if isinstance(check, StyledCheckbutton):
            disabled = raffle or card["event"].key in self._distributed_event_keys
            check.configure(state="disabled" if disabled else "normal")
        enabled = event_enabled.get() and item_enabled.get() and not raffle
        if isinstance(name_label, tk.Label):
            name_label.configure(fg=TEXT if enabled else DISABLED_TEXT)
        if isinstance(quantity_label, tk.Label):
            quantity_label.configure(fg=ACCENT_HOVER if enabled else DISABLED_TEXT)
        split_button = item_row.get("split_button")
        if isinstance(split_button, tk.Button) and isinstance(item, DistributionItem):
            if raffle:
                if split_button.winfo_manager():
                    split_button.pack_forget()
            elif not split_button.winfo_manager():
                split_button.pack(side="right", before=quantity_label, padx=(self._px(8), 0))
            divisible = nickname_lookup_key(item.name) in {
                nickname_lookup_key(name) for name in self.divisible_items
            }
            split_button.configure(text="Делится" if divisible else "Делить", fg=ACCENT if divisible else MUTED)
        raffle_button = item_row.get("raffle_button")
        if isinstance(raffle_button, tk.Button) and isinstance(item, DistributionItem):
            raffle_button.configure(text="Для розыгрыша" if raffle else "В розыгрыш", fg=ACCENT if raffle else MUTED)
        self._refresh_distribute_button()

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self._schedule_scroll_update()

    def _schedule_scroll_update(self) -> None:
        if self._scroll_update_after_id is not None:
            return
        self._scroll_update_after_id = self.after_idle(
            self._run_scroll_update
        )

    def _run_scroll_update(self) -> None:
        self._scroll_update_after_id = None
        self._update_scroll_region()

    def _update_scroll_region(self) -> None:
        if not self.canvas.winfo_exists():
            return
        region = self.canvas.bbox("all")
        if region != self._scroll_region:
            self._scroll_region = region
            self.canvas.configure(scrollregion=region)
        self._update_scrollbar_visibility()

    def _update_scrollbar_visibility(self) -> None:
        if not self.canvas.winfo_exists():
            return
        overflow = self.events_frame.winfo_reqheight() > self.canvas.winfo_height()
        if overflow and not self._scrollbar_visible:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
            self._scrollbar_visible = True
        elif not overflow and self._scrollbar_visible:
            self.scrollbar.grid_remove()
            self._scrollbar_visible = False

    def _resize_events(self, event: tk.Event[tk.Misc]) -> None:
        if self._canvas_width != event.width:
            self._canvas_width = event.width
            self.canvas.itemconfigure(self.events_window, width=event.width)
        self._schedule_scroll_update()

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self.events_frame.winfo_reqheight() > self.canvas.winfo_height():
            direction = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _bind_mousewheel_tree(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._scroll, add="+")
        for child in widget.winfo_children():
            self._bind_mousewheel_tree(child)

    def destroy(self) -> None:
        if self._scroll_update_after_id is not None:
            try:
                self.after_cancel(self._scroll_update_after_id)
            except tk.TclError:
                pass
            self._scroll_update_after_id = None
        for card in self.event_cards:
            job = card.get("copied_label_after_id")
            if isinstance(job, str):
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()
