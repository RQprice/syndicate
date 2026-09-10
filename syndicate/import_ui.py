"""Clipboard screenshot collection, OCR review, and nickname corrections UI."""
from __future__ import annotations

import math
import os
import queue
import threading
import tkinter as tk
from difflib import SequenceMatcher
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from ocr_import import (
    OcrError,
    RecognizedParticipant,
    clipboard_image,
    recognize_participants,
)

from .models import Participant, clean_nickname, format_bm, nickname_lookup_key, parse_bm
from .platform import (
    apply_dark_title_bar,
    apply_window_icon,
    clipboard_sequence_number,
    enable_entry_shortcuts,
    is_foreground_window,
    keep_dark_title_bar,
)
from .theme import (
    ACCENT,
    APP_NAME,
    BACKGROUND,
    BORDER,
    BORDER_LIGHT,
    BUTTON_BORDER,
    DANGER,
    INPUT_BACKGROUND,
    MUTED,
    PANEL_BACKGROUND,
    ROW_HOVER,
    SUCCESS,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_BRIGHT,
)
from .widgets import AnimatedEllipsis, StyledDeleteButton, styled_button


class NicknameCorrectionsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: "ScreenshotImportDialog",
        app: "WheelApp",
    ) -> None:
        super().__init__(parent)
        self.withdraw()
        self.ui_scale = float(getattr(parent, "ui_scale", 1.0))
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.parent_dialog = parent
        self.app = app
        self._scrollbar_visible = False
        self.title("Замены ников")
        apply_window_icon(self)
        self.geometry(f"{self._px(650)}x{self._px(470)}")
        self.minsize(self._px(560), self._px(360))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self._build_ui()
        self.after_idle(self._center_on_parent)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=PANEL_BACKGROUND)
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(20), self._px(12)),
        )
        tk.Label(
            header,
            text="ЗАМЕНЫ НИКОВ",
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
            side="left", padx=(self._px(8), 0), pady=(self._px(2), 0)
        )

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(fill="both", expand=True, padx=self._px(22))

        columns_header = tk.Frame(
            list_shell, bg=SURFACE, height=self._px(30)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        columns_header.grid_columnconfigure(0, weight=1, uniform="corrections")
        columns_header.grid_columnconfigure(1, weight=1, uniform="corrections")
        tk.Label(
            columns_header,
            text="РАСПОЗНАНО",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(self._px(18), 0),
            pady=(self._px(7), self._px(4)),
        )
        tk.Label(
            columns_header,
            text="ИСПОЛЬЗОВАТЬ",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(self._px(18), 0),
            pady=(self._px(7), self._px(4)),
        )
        tk.Frame(list_shell, bg="#343B36", height=self._px(1)).pack(fill="x")

        body = tk.Frame(list_shell, bg=SURFACE)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            body, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            body, orient="vertical", command=self.canvas.yview
        )
        self.rows_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.rows_window = self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_rows)
        self.canvas.bind("<MouseWheel>", self._scroll)

        footer = tk.Frame(self, bg=PANEL_BACKGROUND)
        footer.pack(
            fill="x", padx=self._px(22), pady=self._px(18)
        )
        styled_button(
            footer, "Закрыть", self._close, SURFACE_LIGHT, TEXT
        ).pack(side="right")
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        for widget in self.rows_frame.winfo_children():
            widget.destroy()
        corrections = sorted(
            self.app.nickname_corrections,
            key=lambda correction: nickname_lookup_key(correction.recognized),
        )
        self.count_label.configure(
            text=f"· {len(corrections)}" if corrections else ""
        )
        if not corrections:
            tk.Label(
                self.rows_frame,
                text="Сохранённых замен пока нет",
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 11),
                pady=self._px(28),
            ).pack(fill="x")
        for correction in corrections:
            self._add_row(correction)
        self.canvas.yview_moveto(0.0)
        self.after_idle(self._update_scrollbar_visibility)

    def _add_row(self, correction: NicknameCorrection) -> None:
        row = tk.Frame(self.rows_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(
            row, bg=SURFACE, padx=self._px(16), pady=self._px(8)
        )
        content.pack(fill="x")
        content.grid_columnconfigure(0, weight=1, uniform="correction_values")
        content.grid_columnconfigure(2, weight=1, uniform="correction_values")
        recognized_label = tk.Label(
            content,
            text=correction.recognized,
            bg=SURFACE,
            fg=TEXT,
            anchor="w",
            font=("Segoe UI", 11),
        )
        recognized_label.grid(row=0, column=0, sticky="ew")
        arrow_label = tk.Label(
            content,
            text="⇆",
            bg=SURFACE,
            fg=ACCENT,
            font=("Segoe UI Symbol", 12),
            padx=self._px(14),
        )
        arrow_label.grid(row=0, column=1)
        replacement_label = tk.Label(
            content,
            text=correction.replacement,
            bg=SURFACE,
            fg=TEXT,
            anchor="w",
            font=("Segoe UI", 11),
        )
        replacement_label.grid(row=0, column=2, sticky="ew")
        delete = StyledDeleteButton(
            content,
            command=lambda name=correction.recognized: self._delete(name),
            background=SURFACE,
        )
        delete.grid(row=0, column=3, padx=(self._px(12), 0))
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(
            fill="x", padx=self._px(10)
        )

        def set_hover(hovered: bool) -> None:
            background = ROW_HOVER if hovered else SURFACE
            row.configure(bg=background)
            content.configure(bg=background)
            recognized_label.configure(bg=background)
            arrow_label.configure(bg=background)
            replacement_label.configure(bg=background)
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

        for widget in (row, content, recognized_label, arrow_label, replacement_label, delete):
            widget.bind("<Enter>", lambda _event: set_hover(True), add="+")
            widget.bind("<Leave>", lambda _event: set_hover(False), add="+")
            widget.bind("<MouseWheel>", self._scroll)

    def _delete(self, recognized_name: str) -> None:
        try:
            self.app.remove_nickname_correction(recognized_name)
        except OSError as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось удалить замену:\n{error}",
                parent=self,
            )
            return
        self._refresh_rows()

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
            self.scrollbar.pack_forget()
            self._scrollbar_visible = False

    def _scroll(self, event: tk.Event[tk.Misc]) -> str:
        if self._scrollbar_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _center_on_parent(self) -> None:
        self.update_idletasks()
        width = max(self._px(650), self.winfo_width())
        height = max(self._px(470), self.winfo_height())
        x = self.parent_dialog.winfo_rootx() + (
            self.parent_dialog.winfo_width() - width
        ) // 2
        y = self.parent_dialog.winfo_rooty() + (
            self.parent_dialog.winfo_height() - height
        ) // 2
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        apply_dark_title_bar(self)
        self.deiconify()
        self.after(10, self._finish_open)

    def _finish_open(self) -> None:
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()

    def _close(self) -> None:
        if getattr(self.parent_dialog, "corrections_dialog", None) is self:
            self.parent_dialog.corrections_dialog = None
        self.destroy()

class ScreenshotImportDialog(tk.Toplevel):
    THUMBNAIL_WIDTH = 310
    THUMBNAIL_HEIGHT = 170

    def __init__(self, owner: "ParticipantsPanel") -> None:
        super().__init__(owner.winfo_toplevel())
        self.withdraw()
        self.ui_scale = float(getattr(owner.owner, "ui_scale", 1.0))
        self.thumbnail_width = self._px(self.THUMBNAIL_WIDTH)
        self.thumbnail_height = self._px(self.THUMBNAIL_HEIGHT)
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.owner = owner
        self.screenshots: list[Image.Image] = []
        self.rows: list[dict[str, object]] = []
        self.corrections_dialog: NicknameCorrectionsDialog | None = None
        self.ocr_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.view = "screenshots"
        self._scrollbar_visible = False
        self.loading_text = AnimatedEllipsis(self)
        self._clipboard_watch_after_id: str | None = None
        self._clipboard_was_foreground = False
        self._clipboard_sequence_before_blur = clipboard_sequence_number()
        self._last_imported_clipboard_sequence = 0

        self.title("Импорт из буфера")
        apply_window_icon(self)
        self.geometry(f"{self._px(760)}x{self._px(660)}")
        self.minsize(self._px(700), self._px(540))
        self.configure(bg=PANEL_BACKGROUND)
        self.transient(owner.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)
        keep_dark_title_bar(self)
        self.bind("<Control-KeyPress>", self._on_control_keypress)
        self._build_ui()
        self._prioritize_keyboard_shortcuts()
        self._show_screenshot_view()
        self.after_idle(self._center_on_application)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, round(value * self.ui_scale))

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=PANEL_BACKGROUND)
        header.pack(
            fill="x",
            padx=self._px(22),
            pady=(self._px(20), self._px(12)),
        )
        tk.Label(
            header,
            text="ИМПОРТ ИЗ БУФЕРА",
            bg=PANEL_BACKGROUND,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(side="left")
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg=PANEL_BACKGROUND,
            fg=ACCENT,
            font=("Segoe UI Semibold", 12),
        )
        self.status_label.pack(
            side="left", padx=(self._px(8), 0), pady=(self._px(2), 0)
        )
        self.paste_button = styled_button(
            header, "Вставить скриншот", self._paste, SURFACE_LIGHT, TEXT
        )
        self.paste_button.pack(side="right")
        self.corrections_button = styled_button(
            header, "⇆", self._open_corrections, SURFACE_LIGHT, TEXT
        )
        self.corrections_button.configure(
            font=("Segoe UI Symbol", 13),
            padx=self._px(13),
            pady=self._px(3),
        )
        self.corrections_button.pack(
            side="right", fill="y", padx=(0, self._px(8))
        )

        list_shell = tk.Frame(
            self,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_shell.pack(fill="both", expand=True, padx=self._px(22))
        self.canvas = tk.Canvas(
            list_shell, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self.scrollbar = ttk.Scrollbar(
            list_shell, orient="vertical", command=self.canvas.yview
        )
        self.content_frame = tk.Frame(self.canvas, bg=SURFACE)
        self.content_window = self.canvas.create_window(
            (0, 0), window=self.content_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content_frame.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind("<MouseWheel>", self._scroll)

        footer = tk.Frame(self, bg=PANEL_BACKGROUND)
        footer.pack(
            fill="x", padx=self._px(22), pady=self._px(18)
        )
        self.back_button = styled_button(
            footer, "К скриншотам", self._show_screenshot_view, SURFACE_LIGHT, TEXT
        )
        styled_button(
            footer, "Отмена", self._close, PANEL_BACKGROUND, MUTED
        ).pack(side="right", padx=(self._px(8), 0))
        self.action_button = styled_button(
            footer, "Распознать", self._recognize, SURFACE_LIGHT, TEXT
        )
        self.action_button.pack(side="right")

    def _paste(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self.busy:
            return "break"
        try:
            image = clipboard_image()
        except OcrError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self)
            return "break"

        self.screenshots.append(image.copy())
        self._last_imported_clipboard_sequence = clipboard_sequence_number()
        self._show_screenshot_view()
        return "break"

    def _on_control_keypress(self, event: tk.Event[tk.Misc]) -> str | None:
        if isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return None
        keysym = str(getattr(event, "keysym", "")).casefold()
        keycode = int(getattr(event, "keycode", 0) or 0)
        if keycode == 86 or keysym in {"v", "м", "cyrillic_em"}:
            return self._paste(event)
        return None

    def _prioritize_keyboard_shortcuts(self) -> None:
        """Handle dialog shortcuts before focused Entry and Canvas classes."""

        dialog_tag = str(self)

        def visit(widget: tk.Misc) -> None:
            try:
                tags = tuple(str(tag) for tag in widget.bindtags())
                widget.bindtags(
                    (dialog_tag,) + tuple(tag for tag in tags if tag != dialog_tag)
                )
                children = widget.winfo_children()
            except tk.TclError:
                return
            for child in children:
                visit(child)

        visit(self)

    def _open_corrections(self) -> None:
        if self.busy:
            return
        if (
            self.corrections_dialog is not None
            and self.corrections_dialog.winfo_exists()
        ):
            self.corrections_dialog.deiconify()
            self.corrections_dialog.lift()
            self.corrections_dialog.focus_force()
            return
        self.corrections_dialog = NicknameCorrectionsDialog(
            self, self.owner.owner
        )

    def _show_screenshot_view(self) -> None:
        if self.busy:
            return
        self.view = "screenshots"
        self.rows.clear()
        self._clear_content()
        self.content_frame.grid_columnconfigure(0, weight=1, uniform="screenshots")
        self.content_frame.grid_columnconfigure(1, weight=1, uniform="screenshots")

        for index, screenshot in enumerate(self.screenshots):
            self._add_thumbnail(screenshot, index)

        count = len(self.screenshots)
        self.status_var.set(f"· {count}" if count else "")
        self.paste_button.configure(state="normal", text="Вставить скриншот")
        self.corrections_button.configure(state="normal")
        self.action_button.configure(
            text="Распознать",
            command=self._recognize,
            state="normal" if count else "disabled",
        )
        self.back_button.pack_forget()
        self.canvas.yview_moveto(0.0)
        self.after_idle(self._prioritize_keyboard_shortcuts)
        self.after_idle(self._update_scrollbar_visibility)

    def _add_thumbnail(self, screenshot: Image.Image, index: int) -> None:
        preview = screenshot.convert("RGB")
        preview.thumbnail(
            (self._px(290), self._px(150)), Image.Resampling.LANCZOS
        )
        dim_layer = Image.new("RGB", preview.size, BACKGROUND)
        dimmed = Image.blend(preview, dim_layer, 0.58)
        normal_photo = ImageTk.PhotoImage(preview)
        dimmed_photo = ImageTk.PhotoImage(dimmed)

        card = tk.Canvas(
            self.content_frame,
            width=self.thumbnail_width,
            height=self.thumbnail_height,
            bg=SURFACE_LIGHT,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        card.grid(
            row=index // 2,
            column=index % 2,
            padx=self._px(8),
            pady=self._px(8),
        )
        card.create_rectangle(
            1,
            1,
            self.thumbnail_width - self._px(1),
            self.thumbnail_height - self._px(1),
            outline=BUTTON_BORDER,
            width=self._px(2),
        )
        image_item = card.create_image(
            self.thumbnail_width // 2,
            self.thumbnail_height // 2,
            image=normal_photo,
        )
        card.normal_photo = normal_photo  # type: ignore[attr-defined]
        card.dimmed_photo = dimmed_photo  # type: ignore[attr-defined]

        def show_delete(_event: tk.Event[tk.Misc]) -> None:
            card.itemconfigure(image_item, image=card.dimmed_photo)  # type: ignore[attr-defined]
            center_x = self.thumbnail_width // 2
            center_y = self.thumbnail_height // 2
            card.create_line(
                center_x - self._px(15),
                center_y - self._px(15),
                center_x + self._px(15),
                center_y + self._px(15),
                fill=TEXT,
                width=self._px(4),
                capstyle="round",
                tags="delete_overlay",
            )
            card.create_line(
                center_x + self._px(15),
                center_y - self._px(15),
                center_x - self._px(15),
                center_y + self._px(15),
                fill=TEXT,
                width=self._px(4),
                capstyle="round",
                tags="delete_overlay",
            )

        def hide_delete(_event: tk.Event[tk.Misc]) -> None:
            card.itemconfigure(image_item, image=card.normal_photo)  # type: ignore[attr-defined]
            card.delete("delete_overlay")

        card.bind("<Enter>", show_delete)
        card.bind("<Leave>", hide_delete)
        card.bind(
            "<Button-1>",
            lambda _event, image=screenshot: self._delete_screenshot(image),
        )
        card.bind("<MouseWheel>", self._scroll)

    def _delete_screenshot(self, screenshot: Image.Image) -> None:
        if self.busy:
            return
        for index, current in enumerate(self.screenshots):
            if current is screenshot:
                del self.screenshots[index]
                break
        self._show_screenshot_view()

    def _recognize(self) -> None:
        if self.busy or not self.screenshots:
            return
        self.busy = True
        self.paste_button.configure(state="disabled")
        self.corrections_button.configure(state="disabled")
        self.action_button.configure(state="disabled")
        self.loading_text.start(self.action_button, "Распознавание")
        images = [image.copy() for image in self.screenshots]

        def worker() -> None:
            try:
                result: list[RecognizedParticipant] = []
                for image in images:
                    result.extend(recognize_participants(image))
                self.ocr_queue.put(("result", result))
            except Exception as error:
                self.ocr_queue.put(("error", error))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_ocr)
        return "break"

    def _poll_ocr(self) -> None:
        try:
            kind, payload = self.ocr_queue.get_nowait()
        except queue.Empty:
            if self.busy:
                self.after(100, self._poll_ocr)
            return

        self.busy = False
        self.loading_text.stop()
        if kind == "error":
            self._show_screenshot_view()
            messagebox.showerror(
                APP_NAME,
                str(payload) or "Не удалось распознать изображение.",
                parent=self,
            )
            return

        recognized = payload if isinstance(payload, list) else []
        if not recognized:
            self._show_screenshot_view()
            messagebox.showwarning(
                APP_NAME, "На изображении не найдены участники.", parent=self
            )
            return
        self._show_results()
        for participant in recognized:
            if isinstance(participant, RecognizedParticipant):
                self._merge_or_add(participant)
        self.status_var.set(f"· {len(self.rows)}")
        self.action_button.configure(state="normal" if self.rows else "disabled")

    def _show_results(self) -> None:
        self.view = "results"
        self.rows.clear()
        self._clear_content()
        self.paste_button.configure(state="normal", text="Вставить скриншот")
        self.corrections_button.configure(state="normal")
        self.action_button.configure(
            text="Добавить",
            command=self._apply,
            state="disabled",
        )
        columns_header = tk.Frame(
            self.content_frame, bg=SURFACE, height=self._px(28)
        )
        columns_header.pack(fill="x")
        columns_header.pack_propagate(False)
        tk.Label(
            columns_header,
            text="ИГРОК",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(
            side="left",
            padx=(self._px(20), 0),
            pady=(self._px(7), self._px(4)),
        )
        tk.Label(
            columns_header,
            text="БМ",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(
            side="right",
            padx=(0, self._px(58)),
            pady=(self._px(7), self._px(4)),
        )
        tk.Frame(
            self.content_frame, bg="#343B36", height=self._px(1)
        ).pack(fill="x")
        self.back_button.pack(side="left")
        self.canvas.yview_moveto(0.0)
        self.after_idle(self._prioritize_keyboard_shortcuts)

    def _merge_or_add(self, participant: RecognizedParticipant) -> bool:
        recognized_name = clean_nickname(participant.name)
        corrected_name = self.owner.owner.corrected_nickname(recognized_name)
        new_name = self._normalized_participant_name(corrected_name)
        for row in self.rows:
            name_var = row.get("name")
            bm_var = row.get("bm")
            confidence = float(row.get("confidence", 0.0))
            if not isinstance(name_var, tk.StringVar) or not isinstance(
                bm_var, tk.StringVar
            ):
                continue
            current_name = self._normalized_participant_name(name_var.get())
            try:
                current_bm = int(bm_var.get().replace(" ", ""))
            except ValueError:
                current_bm = -1
            similarity = SequenceMatcher(None, current_name, new_name).ratio()
            same_person = current_name == new_name or (
                current_bm == participant.bm and similarity >= 0.72
            )
            if same_person:
                if (
                    participant.confidence > confidence
                    and not bool(row.get("name_edited"))
                ):
                    row["recognized_name"] = recognized_name
                    row["initial_name"] = corrected_name
                    name_var.set(corrected_name)
                    row["name_edited"] = False
                    bm_var.set(format_bm(float(participant.bm)))
                    row["confidence"] = participant.confidence
                return False
        self._add_result_row(participant, corrected_name, recognized_name)
        return True

    def _add_result_row(
        self,
        participant: RecognizedParticipant,
        corrected_name: str,
        recognized_name: str,
    ) -> None:
        row = tk.Frame(self.content_frame, bg=SURFACE)
        row.pack(fill="x")
        content = tk.Frame(
            row, bg=SURFACE, padx=self._px(12), pady=self._px(3)
        )
        content.pack(fill="x")
        tk.Frame(row, bg="#343B36", height=self._px(1)).pack(
            fill="x", padx=self._px(10)
        )

        name_var = tk.StringVar(value=corrected_name)
        normal_name_border = (
            DANGER if participant.confidence < 55 else BORDER
        )
        name_field = tk.Frame(
            content,
            bg=SURFACE,
            highlightthickness=1 if participant.confidence < 55 else 0,
            highlightbackground=normal_name_border,
        )
        name_field.pack(side="left", fill="x", expand=True)
        name_entry = tk.Entry(
            name_field,
            textvariable=name_var,
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 11),
            highlightthickness=0,
        )
        enable_entry_shortcuts(name_entry)
        name_entry.pack(
            side="left", fill="both", expand=True, ipady=self._px(7)
        )
        new_badge = tk.Label(
            name_field,
            text="NEW",
            bg=ACCENT,
            fg=BACKGROUND,
            font=("Segoe UI Semibold", 8),
            padx=self._px(7),
            pady=self._px(2),
        )
        update_badge = tk.Label(
            name_field,
            text="UPD",
            bg=SUCCESS,
            fg=TEXT_BRIGHT,
            font=("Segoe UI Semibold", 8),
            padx=self._px(7),
            pady=self._px(2),
        )
        bm_var = tk.StringVar(value=format_bm(float(participant.bm)))
        bm_entry = tk.Entry(
            content,
            textvariable=bm_var,
            width=10,
            justify="right",
            bg=SURFACE,
            fg=MUTED,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
            highlightthickness=0,
            highlightbackground=SURFACE,
            highlightcolor=BORDER_LIGHT,
        )
        enable_entry_shortcuts(bm_entry)
        bm_entry.pack(
            side="left",
            padx=(self._px(12), 0),
            ipady=self._px(7),
        )
        row_data: dict[str, object] = {
            "frame": row,
            "content": content,
            "name": name_var,
            "name_entry": name_entry,
            "name_field": name_field,
            "bm": bm_var,
            "bm_entry": bm_entry,
            "confidence": participant.confidence,
            "recognized_name": recognized_name,
            "initial_name": corrected_name,
            "name_edited": False,
            "hovered": False,
        }
        delete_button = StyledDeleteButton(
            content,
            command=lambda data=row_data: self._delete_row(data),
            background=SURFACE,
        )
        delete_button.pack(side="right", padx=(self._px(10), 0))
        row_data["delete"] = delete_button
        row_data["new_badge"] = new_badge
        row_data["update_badge"] = update_badge
        self.rows.append(row_data)
        name_var.trace_add(
            "write",
            lambda *_args, data=row_data: self._on_result_name_changed(data),
        )
        bm_var.trace_add(
            "write",
            lambda *_args, data=row_data: self._update_result_badges(data),
        )
        self._update_result_badges(row_data)
        name_entry.bind(
            "<FocusIn>",
            lambda _event, data=row_data: self._set_result_entry_focus(
                data, True, True
            ),
        )
        name_entry.bind(
            "<FocusOut>",
            lambda _event, data=row_data: self._set_result_entry_focus(
                data, False, True
            ),
        )
        bm_entry.bind(
            "<FocusIn>",
            lambda _event, data=row_data: self._set_result_entry_focus(
                data, True, False
            ),
        )
        bm_entry.bind(
            "<FocusOut>",
            lambda _event, data=row_data: self._finish_result_bm_edit(data),
        )
        hover_widgets = (
            row,
            content,
            name_field,
            name_entry,
            new_badge,
            update_badge,
            bm_entry,
            delete_button,
        )
        for widget in hover_widgets:
            widget.bind(
                "<Enter>",
                lambda _event, data=row_data: self._set_result_row_hover(
                    data, True
                ),
                add="+",
            )
            widget.bind(
                "<Leave>",
                lambda _event, data=row_data: self.after_idle(
                    lambda item=data: self._finish_result_row_leave(item)
                ),
                add="+",
            )
            widget.bind("<MouseWheel>", self._scroll)
        self._update_result_row_appearance(row_data)
        self.after_idle(self._prioritize_keyboard_shortcuts)
        self.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def _set_result_entry_focus(
        self,
        row_data: dict[str, object],
        focused: bool,
        name_field: bool,
    ) -> None:
        field = row_data.get("name_field")
        name_entry = row_data.get("name_entry")
        bm_entry = row_data.get("bm_entry")
        if name_field and isinstance(field, tk.Frame) and isinstance(
            name_entry, tk.Entry
        ):
            if focused:
                field.configure(
                    bg=INPUT_BACKGROUND,
                    highlightthickness=1,
                    highlightbackground=BORDER_LIGHT,
                )
                name_entry.configure(bg=INPUT_BACKGROUND)
            else:
                self._update_result_row_appearance(row_data)
        elif not name_field and isinstance(bm_entry, tk.Entry):
            if focused:
                bm_entry.configure(
                    bg=INPUT_BACKGROUND,
                    fg=TEXT,
                    highlightthickness=1,
                    highlightbackground=BORDER_LIGHT,
                )
            else:
                self._update_result_row_appearance(row_data)

    def _finish_result_bm_edit(self, row_data: dict[str, object]) -> None:
        bm_var = row_data.get("bm")
        if isinstance(bm_var, tk.StringVar):
            try:
                bm_var.set(format_bm(parse_bm(bm_var.get())))
            except ValueError:
                pass
        self._set_result_entry_focus(row_data, False, False)

    def _update_result_row_appearance(
        self, row_data: dict[str, object]
    ) -> None:
        background = ROW_HOVER if row_data.get("hovered") else SURFACE
        frame = row_data.get("frame")
        content = row_data.get("content")
        name_field = row_data.get("name_field")
        name_entry = row_data.get("name_entry")
        bm_entry = row_data.get("bm_entry")
        delete = row_data.get("delete")
        confidence = float(row_data.get("confidence", 0.0))
        if isinstance(frame, tk.Frame):
            frame.configure(bg=background)
        if isinstance(content, tk.Frame):
            content.configure(bg=background)
        if isinstance(name_field, tk.Frame) and isinstance(name_entry, tk.Entry):
            if name_entry.focus_get() is not name_entry:
                name_field.configure(
                    bg=background,
                    highlightthickness=1 if confidence < 55 else 0,
                    highlightbackground=DANGER if confidence < 55 else background,
                )
                name_entry.configure(bg=background)
        if isinstance(bm_entry, tk.Entry) and bm_entry.focus_get() is not bm_entry:
            bm_entry.configure(
                bg=background,
                fg=MUTED,
                highlightthickness=0,
                highlightbackground=background,
            )
        if isinstance(delete, StyledDeleteButton):
            delete.base_background = background
            delete.configure(bg=background)
            delete._redraw()

    def _set_result_row_hover(
        self, row_data: dict[str, object], hovered: bool
    ) -> None:
        if bool(row_data.get("hovered")) == hovered:
            return
        row_data["hovered"] = hovered
        self._update_result_row_appearance(row_data)

    def _finish_result_row_leave(self, row_data: dict[str, object]) -> None:
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
        self._set_result_row_hover(row_data, False)

    @staticmethod
    def _normalized_participant_name(name: str) -> str:
        return nickname_lookup_key(name)

    def _on_result_name_changed(
        self, row_data: dict[str, object]
    ) -> None:
        name_var = row_data.get("name")
        if isinstance(name_var, tk.StringVar):
            initial_name = clean_nickname(str(row_data.get("initial_name", "")))
            current_name = clean_nickname(name_var.get())
            row_data["name_edited"] = current_name != initial_name
        self._update_result_badges(row_data)

    def _existing_participant_bm(self, name: str) -> float | None:
        normalized = self._normalized_participant_name(name)
        if not normalized:
            return None
        for participant_row in self.owner.rows:
            existing_name = participant_row.get("name")
            existing_bm = participant_row.get("bm")
            if isinstance(existing_name, tk.StringVar):
                if self._normalized_participant_name(existing_name.get()) == normalized:
                    if not isinstance(existing_bm, tk.StringVar):
                        return None
                    try:
                        return parse_bm(existing_bm.get())
                    except ValueError:
                        return None
        return None

    def _update_result_badges(self, row_data: dict[str, object]) -> None:
        name_var = row_data.get("name")
        bm_var = row_data.get("bm")
        new_badge = row_data.get("new_badge")
        update_badge = row_data.get("update_badge")
        if (
            not isinstance(name_var, tk.StringVar)
            or not isinstance(bm_var, tk.StringVar)
            or not isinstance(new_badge, tk.Label)
            or not isinstance(update_badge, tk.Label)
        ):
            return
        normalized_name = self._normalized_participant_name(name_var.get())
        existing_bm = self._existing_participant_bm(name_var.get())
        is_new = bool(normalized_name) and existing_bm is None
        try:
            imported_bm = parse_bm(bm_var.get())
        except ValueError:
            imported_bm = math.nan
        is_updated = (
            not is_new
            and existing_bm is not None
            and math.isfinite(imported_bm)
            and not math.isclose(imported_bm, existing_bm)
        )

        for badge, visible in (
            (new_badge, is_new),
            (update_badge, is_updated),
        ):
            if visible and not badge.winfo_manager():
                badge.pack(
                    side="right",
                    padx=(self._px(6), self._px(6)),
                    pady=self._px(5),
                )
            elif not visible and badge.winfo_manager():
                badge.pack_forget()

    def _delete_row(self, row_data: dict[str, object]) -> None:
        frame = row_data.get("frame")
        if isinstance(frame, tk.Widget):
            frame.destroy()
        self.rows.remove(row_data)
        self.status_var.set(f"· {len(self.rows)}" if self.rows else "")
        self.action_button.configure(state="normal" if self.rows else "disabled")

    def _apply(self) -> None:
        imported: list[Participant] = []
        correction_updates: list[tuple[str, str]] = []
        for row in self.rows:
            name_var = row.get("name")
            bm_var = row.get("bm")
            if not isinstance(name_var, tk.StringVar) or not isinstance(
                bm_var, tk.StringVar
            ):
                continue
            name = " ".join(name_var.get().strip().split())
            try:
                bm = int(bm_var.get().replace(" ", ""))
            except ValueError:
                bm = -1
            if not name or bm < 0:
                messagebox.showwarning(
                    APP_NAME, "Проверьте имя и БМ в результатах.", parent=self
                )
                return
            imported.append(Participant(name[:40], False, float(bm)))
            recognized_name = clean_nickname(
                str(row.get("recognized_name", ""))
            )
            if bool(row.get("name_edited")) and recognized_name:
                correction_updates.append((recognized_name, name[:40]))
        if correction_updates:
            try:
                self.owner.owner.remember_nickname_corrections(
                    correction_updates
                )
            except OSError as error:
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось сохранить замену ника:\n{error}",
                    parent=self,
                )
                return
        if imported:
            self.owner.apply_import(imported)
        self._close()

    def _clear_content(self) -> None:
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

    def _sync_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._update_scrollbar_visibility)

    def _resize_content(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.content_window, width=event.width)
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

    def _start_clipboard_watch(self) -> None:
        if self._clipboard_watch_after_id is not None:
            return
        self._clipboard_was_foreground = is_foreground_window(self)
        self._clipboard_sequence_before_blur = clipboard_sequence_number()
        self._clipboard_watch_after_id = self.after(
            180, self._poll_clipboard_history
        )

    def _poll_clipboard_history(self) -> None:
        self._clipboard_watch_after_id = None
        if not self.winfo_exists():
            return
        foreground = is_foreground_window(self)
        sequence = clipboard_sequence_number()
        if not foreground and self._clipboard_was_foreground:
            self._clipboard_sequence_before_blur = sequence
        elif foreground and not self._clipboard_was_foreground:
            clipboard_changed = (
                sequence
                and sequence != self._clipboard_sequence_before_blur
                and sequence != self._last_imported_clipboard_sequence
            )
            if clipboard_changed:
                self.after(
                    60,
                    lambda revision=sequence: self._paste_clipboard_history(
                        revision
                    ),
                )
        self._clipboard_was_foreground = foreground
        self._clipboard_watch_after_id = self.after(
            180, self._poll_clipboard_history
        )

    def _paste_clipboard_history(self, expected_sequence: int) -> None:
        if (
            self.busy
            or expected_sequence == self._last_imported_clipboard_sequence
            or clipboard_sequence_number() != expected_sequence
        ):
            return
        try:
            image = clipboard_image()
        except OcrError:
            # Win+V can also be used for text; that should remain a normal
            # Windows paste and must not produce an image warning here.
            return
        self.screenshots.append(image.copy())
        self._last_imported_clipboard_sequence = expected_sequence
        self._show_screenshot_view()

    def _close(self) -> None:
        self.loading_text.stop()
        if self._clipboard_watch_after_id is not None:
            try:
                self.after_cancel(self._clipboard_watch_after_id)
            except tk.TclError:
                pass
            self._clipboard_watch_after_id = None
        if getattr(self.owner, "import_dialog", None) is self:
            self.owner.import_dialog = None
        self.destroy()

    def _center_on_application(self) -> None:
        self.update_idletasks()
        application = self.owner.winfo_toplevel()
        frame_offset_x = self.winfo_rootx() - self.winfo_x()
        frame_offset_y = self.winfo_rooty() - self.winfo_y()
        dialog_width = max(self._px(760), self.winfo_width())
        dialog_height = max(self._px(660), self.winfo_height())
        x = application.winfo_rootx() + (
            application.winfo_width() - dialog_width
        ) // 2 - frame_offset_x
        y = application.winfo_rooty() + (
            application.winfo_height() - dialog_height
        ) // 2 - frame_offset_y
        self._open_geometry = (
            f"{dialog_width}x{dialog_height}+{max(0, x)}+{max(0, y)}"
        )
        if os.name == "nt":
            self.geometry(f"{dialog_width}x{dialog_height}-32000-32000")
        else:
            self.geometry(self._open_geometry)
        apply_dark_title_bar(self)
        self.deiconify()
        if os.name == "nt":
            self.attributes("-alpha", 0.0)
        self.update_idletasks()
        apply_dark_title_bar(self)
        self.after(30, self._finish_open)

    def _finish_open(self) -> None:
        apply_dark_title_bar(self)
        self.geometry(self._open_geometry)
        self.update_idletasks()
        apply_dark_title_bar(self)
        if os.name == "nt":
            self.attributes("-alpha", 1.0)
        apply_dark_title_bar(self)
        self.lift()
        self.focus_force()
        self.after(120, self._start_clipboard_watch)
