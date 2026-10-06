"""Winner-penalty settings dialog."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from .models import PenaltySettings
from .platform import (
    apply_dark_title_bar,
    apply_window_icon,
    enable_entry_shortcuts,
    keep_dark_title_bar,
)
from .theme import (
    ACCENT,
    ACCENT_DARK,
    APP_NAME,
    BORDER,
    BORDER_LIGHT,
    INPUT_BACKGROUND,
    MUTED,
    PANEL_BACKGROUND,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    CTA_DISABLED,
)
from .widgets import StyledCheckbutton, styled_button


class PenaltySettingsDialog(tk.Toplevel):
    """Edit the participation-based chance recovery scale."""

    MIN_RECOVERY_PARTICIPATIONS = 1

    def __init__(
        self,
        owner: "ParticipantsPanel",
        settings: PenaltySettings,
    ) -> None:
        super().__init__(owner.winfo_toplevel())
        self.withdraw()
        self.owner = owner
        self.ui_scale = float(getattr(owner, "ui_scale", 1.0))
        self.initial_settings = settings
        self.enabled_var = tk.BooleanVar(value=settings.enabled)
        self.recovery_count = settings.recovery_participations
        self.stage_values = [value * 100.0 for value in settings.chance_steps]
        self.stage_vars: list[tk.StringVar] = []
        self.stage_entries: list[tk.Entry] = []
        self._building_stages = False
        self._stages_scrollbar_visible = False
        self._open_geometry = ""
        self._center_after_id: str | None = None
        self._open_after_id: str | None = None
        if os.name == "nt":
            self.attributes("-alpha", 0.0)

        self.title("Настройка штрафов")
        apply_window_icon(self)
        self.geometry(f"{self._px(680)}x{self._px(660)}")
        self.minsize(self._px(600), self._px(560))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(owner.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self._build_ui()
        self._center_after_id = self.after_idle(self._center_on_application)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    @staticmethod
    def _format_percent(value: float) -> str:
        return (
            str(int(value))
            if float(value).is_integer()
            else f"{value:.2f}".rstrip("0").rstrip(".")
        )

    @staticmethod
    def _participation_caption(value: int) -> str:
        remainder_100 = value % 100
        remainder_10 = value % 10
        if remainder_10 == 1 and remainder_100 != 11:
            noun = "участия"
        else:
            noun = "участий"
        return f"{value} {noun}"

    def _build_ui(self) -> None:
        settings_card = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        settings_card.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(22), 0),
        )

        enabled_row = tk.Frame(settings_card, bg=SURFACE)
        enabled_row.pack(
            fill="x",
            padx=self._px(18),
            pady=(self._px(14), self._px(12)),
        )
        self.enabled_check = StyledCheckbutton(
            enabled_row,
            variable=self.enabled_var,
            background=SURFACE,
        )
        self.enabled_check.pack(side="left")
        enabled_label = tk.Label(
            enabled_row,
            text="Использовать штраф после победы",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
            cursor="hand2",
        )
        enabled_label.pack(side="left", padx=(self._px(9), 0))
        enabled_label.bind(
            "<Button-1>",
            lambda _event: self.enabled_var.set(not self.enabled_var.get()),
        )

        tk.Frame(settings_card, bg=BORDER, height=self._px(1)).pack(fill="x")
        count_row = tk.Frame(settings_card, bg=SURFACE)
        count_row.pack(
            fill="x",
            padx=self._px(18),
            pady=self._px(14),
        )
        count_copy = tk.Frame(count_row, bg=SURFACE)
        count_copy.pack(side="left", fill="x", expand=True)
        tk.Label(
            count_copy,
            text="До полного восстановления",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w")
        tk.Label(
            count_copy,
            text="Считаются только розыгрыши, в которых игрок участвовал",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(self._px(2), 0))

        count_controls = tk.Frame(count_row, bg=SURFACE)
        count_controls.pack(side="right", padx=(self._px(14), 0))
        self.minus_button = styled_button(
            count_controls, "−", lambda: self._change_count(-1), SURFACE_LIGHT, TEXT
        )
        self.minus_button.configure(width=2, padx=self._px(7))
        self.minus_button.pack(side="left")
        self.count_label = tk.Label(
            count_controls,
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            width=11,
            padx=self._px(6),
            pady=self._px(8),
            font=("Segoe UI Semibold", 10),
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.count_label.pack(side="left", padx=self._px(6))
        self.plus_button = styled_button(
            count_controls, "+", lambda: self._change_count(1), SURFACE_LIGHT, TEXT
        )
        self.plus_button.configure(width=2, padx=self._px(7))
        self.plus_button.pack(side="left")

        scale_header = tk.Frame(self, bg=PANEL_BACKGROUND)
        scale_header.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(20), self._px(8)),
        )
        tk.Label(
            scale_header,
            text="ШКАЛА ШАНСА",
            bg=PANEL_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        tk.Label(
            scale_header,
            text="коэффициент",
            bg=PANEL_BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side="right")

        stages_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        stages_shell.pack(
            fill="both",
            expand=True,
            padx=self._px(24),
        )
        self.stages_canvas = tk.Canvas(
            stages_shell,
            bg=SURFACE,
            highlightthickness=0,
            borderwidth=0,
        )
        self.stages_scrollbar = ttk.Scrollbar(
            stages_shell,
            orient="vertical",
            command=self.stages_canvas.yview,
        )
        self.stages_frame = tk.Frame(self.stages_canvas, bg=SURFACE)
        self.stages_window = self.stages_canvas.create_window(
            (0, 0),
            window=self.stages_frame,
            anchor="nw",
        )
        self.stages_canvas.configure(yscrollcommand=self.stages_scrollbar.set)
        self.stages_canvas.pack(side="left", fill="both", expand=True)
        self.stages_frame.bind("<Configure>", self._sync_stages_scroll_region)
        self.stages_canvas.bind("<Configure>", self._resize_stages_content)
        self.bind("<MouseWheel>", self._scroll_stages, add="+")

        footer = tk.Frame(self, bg=PANEL_BACKGROUND)
        footer.pack(
            fill="x",
            padx=self._px(24),
            pady=(self._px(16), self._px(20)),
        )
        self.apply_button = styled_button(
            footer, "Применить", self._apply, ACCENT, "#161713"
        )
        self.apply_button.pack(side="right")
        self.cancel_button = styled_button(
            footer, "Отмена", self._close, SURFACE_LIGHT, TEXT
        )
        self.cancel_button.pack(side="right", padx=(0, self._px(9)))

        self.enabled_var.trace_add("write", self._on_enabled_changed)
        self._rebuild_stage_rows()

    def _stage_caption(self, index: int) -> str:
        if index == 0:
            return "Сразу после победы"
        if index == self.recovery_count:
            return f"После {self._participation_caption(index)} · полный шанс"
        return f"После {self._participation_caption(index)}"

    def _rebuild_stage_rows(self) -> None:
        self._building_stages = True
        for child in self.stages_frame.winfo_children():
            child.destroy()
        self.stage_vars = []
        self.stage_entries = []
        for index, value in enumerate(self.stage_values):
            row = tk.Frame(self.stages_frame, bg=SURFACE)
            row.pack(
                fill="x",
                padx=self._px(16),
                pady=(self._px(9), 0),
            )
            tk.Label(
                row,
                text=str(index + 1),
                bg=SURFACE_LIGHT,
                fg=ACCENT,
                width=3,
                pady=self._px(6),
                font=("Segoe UI Semibold", 9),
            ).pack(side="left")
            tk.Label(
                row,
                text=self._stage_caption(index),
                bg=SURFACE,
                fg=TEXT,
                font=("Segoe UI", 10),
            ).pack(side="left", padx=(self._px(12), 0))
            suffix = tk.Label(
                row,
                text="%",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI Semibold", 10),
            )
            suffix.pack(side="right", padx=(self._px(7), 0))
            variable = tk.StringVar(value=self._format_percent(value))
            variable.trace_add("write", self._refresh_apply_state)
            self.stage_vars.append(variable)
            entry = tk.Entry(
                row,
                textvariable=variable,
                width=7,
                justify="center",
                bg=INPUT_BACKGROUND,
                fg=TEXT,
                insertbackground=TEXT,
                disabledbackground=SURFACE_LIGHT,
                disabledforeground=MUTED,
                relief="flat",
                font=("Segoe UI", 10),
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=BORDER_LIGHT,
            )
            enable_entry_shortcuts(entry)
            entry.pack(side="right", ipady=self._px(5))
            self.stage_entries.append(entry)
            if index == self.recovery_count:
                entry.configure(state="disabled")
            elif not self.enabled_var.get():
                entry.configure(state="disabled")
        self._building_stages = False
        self._refresh_count_controls()
        self._refresh_apply_state()
        self.after_idle(self._update_stages_scrollbar_visibility)

    def _read_editable_values(self) -> bool:
        values: list[float] = []
        for index, variable in enumerate(self.stage_vars):
            if index == self.recovery_count:
                values.append(100.0)
                continue
            try:
                value = float(variable.get().strip().replace(",", "."))
            except ValueError:
                return False
            if not 0 < value <= 100:
                return False
            values.append(value)
        self.stage_values = values
        return True

    def _change_count(self, delta: int) -> None:
        if not self.enabled_var.get() or not self._read_editable_values():
            return
        target = max(
            self.MIN_RECOVERY_PARTICIPATIONS,
            self.recovery_count + delta,
        )
        if target == self.recovery_count:
            return
        if target > self.recovery_count:
            previous = self.stage_values[-2]
            self.stage_values.insert(-1, previous + (100.0 - previous) / 2.0)
        else:
            self.stage_values.pop(-2)
        self.recovery_count = target
        self._rebuild_stage_rows()

    def _refresh_count_controls(self) -> None:
        self.count_label.configure(
            text=self._participation_caption(self.recovery_count)
        )
        enabled = self.enabled_var.get()
        self.minus_button.configure(
            state=(
                "normal"
                if enabled
                and self.recovery_count > self.MIN_RECOVERY_PARTICIPATIONS
                else "disabled"
            )
        )
        self.plus_button.configure(
            state="normal" if enabled else "disabled"
        )

    def _on_enabled_changed(self, *_args: object) -> None:
        enabled = self.enabled_var.get()
        for index, entry in enumerate(self.stage_entries):
            entry.configure(
                state=(
                    "normal"
                    if enabled and index < self.recovery_count
                    else "disabled"
                )
            )
        self._refresh_count_controls()
        self._refresh_apply_state()

    def _settings_from_controls(self) -> PenaltySettings | None:
        values: list[float] = []
        for index, variable in enumerate(self.stage_vars):
            if index == self.recovery_count:
                values.append(100.0)
                continue
            try:
                value = float(variable.get().strip().replace(",", "."))
            except ValueError:
                return None
            if not 0 < value <= 100:
                return None
            values.append(value)
        if any(
            current < previous
            for previous, current in zip(values, values[1:])
        ):
            return None
        return PenaltySettings(
            enabled=self.enabled_var.get(),
            chance_steps=tuple(value / 100.0 for value in values),
        )

    def _refresh_apply_state(self, *_args: object) -> None:
        if self._building_stages:
            return
        settings = self._settings_from_controls()
        changed = settings is not None and settings != self.initial_settings
        if changed:
            self.apply_button.configure(
                state="normal",
                bg=ACCENT,
                highlightbackground=ACCENT_DARK,
                highlightcolor=ACCENT_DARK,
            )
        else:
            self.apply_button.configure(
                state="disabled",
                bg=CTA_DISABLED,
                highlightbackground=CTA_DISABLED,
                highlightcolor=CTA_DISABLED,
            )

    def _sync_stages_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.stages_canvas.configure(scrollregion=self.stages_canvas.bbox("all"))
        self.after_idle(self._update_stages_scrollbar_visibility)

    def _resize_stages_content(self, event: tk.Event[tk.Misc]) -> None:
        self.stages_canvas.itemconfigure(self.stages_window, width=event.width)
        self.after_idle(self._update_stages_scrollbar_visibility)

    def _update_stages_scrollbar_visibility(self) -> None:
        bbox = self.stages_canvas.bbox("all")
        content_height = 0 if bbox is None else bbox[3] - bbox[1]
        should_show = content_height > self.stages_canvas.winfo_height() + 1
        if should_show and not self._stages_scrollbar_visible:
            self.stages_scrollbar.pack(side="right", fill="y")
            self._stages_scrollbar_visible = True
        elif not should_show and self._stages_scrollbar_visible:
            self.stages_canvas.yview_moveto(0.0)
            self.stages_scrollbar.pack_forget()
            self._stages_scrollbar_visible = False

    def _scroll_stages(self, event: tk.Event[tk.Misc]) -> str | None:
        if not self._stages_scrollbar_visible:
            return None
        self.stages_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _apply(self) -> None:
        if not self._read_editable_values():
            messagebox.showwarning(
                APP_NAME,
                "Укажите шанс от 1 до 100% для каждого этапа.",
                parent=self,
            )
            return
        if any(
            current < previous
            for previous, current in zip(
                self.stage_values,
                self.stage_values[1:],
            )
        ):
            messagebox.showwarning(
                APP_NAME,
                "Шанс на каждом следующем этапе не должен уменьшаться.",
                parent=self,
            )
            return
        settings = self._settings_from_controls()
        if settings is None or settings == self.initial_settings:
            self._refresh_apply_state()
            return
        try:
            self.owner.apply_penalty_settings(settings)
        except OSError as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось сохранить настройки штрафов:\n{error}",
                parent=self,
            )
            return
        self._close()

    def _center_on_application(self) -> None:
        self._center_after_id = None
        self.update_idletasks()
        application = self.owner.winfo_toplevel()
        width = max(self._px(680), self.winfo_width())
        height = max(self._px(660), self.winfo_height())
        x = application.winfo_rootx() + (application.winfo_width() - width) // 2
        y = application.winfo_rooty() + (application.winfo_height() - height) // 2
        self._open_geometry = f"{width}x{height}+{max(0, x)}+{max(0, y)}"
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
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _close(self) -> None:
        for attribute in ("_center_after_id", "_open_after_id"):
            callback_id = getattr(self, attribute, None)
            if callback_id is None:
                continue
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)
        if getattr(self.owner, "penalty_dialog", None) is self:
            self.owner.penalty_dialog = None
        self.destroy()


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .participants_ui import ParticipantsPanel
