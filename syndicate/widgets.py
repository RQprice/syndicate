"""Reusable themed Tk widgets used by multiple screens."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from PIL import Image, ImageColor, ImageTk

from ocr_import import OcrError, clipboard_image

from .platform import enable_entry_shortcuts, scaled_px, widget_ui_scale
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    APP_NAME,
    BACKGROUND,
    BORDER,
    BORDER_LIGHT,
    BRAND_GREEN,
    BRAND_GREEN_LIGHT,
    BUTTON_BORDER,
    BUTTON_HOVER,
    BUTTON_HOVER_BORDER,
    CTA_BACKGROUND,
    CTA_BORDER,
    CTA_HOVER,
    CTA_HOVER_BORDER,
    CTA_PRESSED,
    DISABLED_TEXT,
    INPUT_BACKGROUND,
    MUTED,
    NICKNAME_BACKGROUND,
    NICKNAME_HOVER,
    SURFACE,
    SURFACE_LIGHT,
    TEXT,
    TEXT_BRIGHT,
    WINNER_BACKGROUND,
)


class AnimatedEllipsis:
    """Animate trailing dots on a button while a background task is active."""

    INTERVAL_MS = 320
    DOT_SLOTS = 3
    PUNCTUATION_SPACE = "\u2008"

    def __init__(self, owner: tk.Misc) -> None:
        self.owner = owner
        self.widget: tk.Widget | None = None
        self.base_text = ""
        self.phase = 0
        self.after_id: str | None = None

    def start(self, widget: tk.Widget, base_text: str) -> None:
        self.stop()
        self.widget = widget
        self.base_text = base_text.rstrip(". …")
        self.phase = 0
        self._tick()

    def stop(self) -> None:
        if self.after_id is not None:
            try:
                self.owner.after_cancel(self.after_id)
            except tk.TclError:
                pass
        self.after_id = None
        self.widget = None

    def _tick(self) -> None:
        widget = self.widget
        if widget is None:
            return
        try:
            if not widget.winfo_exists():
                self.stop()
                return
            visible_dots = "." * self.phase
            reserved_dots = self.PUNCTUATION_SPACE * (
                self.DOT_SLOTS - self.phase
            )
            widget.configure(
                text=self.base_text + visible_dots + reserved_dots
            )
        except tk.TclError:
            self.stop()
            return
        self.phase = (self.phase + 1) % (self.DOT_SLOTS + 1)
        self.after_id = self.owner.after(self.INTERVAL_MS, self._tick)


def styled_button(
    parent: tk.Misc,
    text: str,
    command: object,
    background: str,
    foreground: str,
) -> tk.Button:
    if background == ACCENT:
        hover_background = ACCENT_HOVER
        normal_border = ACCENT_DARK
        hover_border = ACCENT_HOVER
    elif background in (SURFACE, SURFACE_LIGHT):
        hover_background = BUTTON_HOVER
        normal_border = BUTTON_BORDER
        hover_border = BUTTON_HOVER_BORDER
    else:
        hover_background = SURFACE_LIGHT
        normal_border = background
        hover_border = BUTTON_BORDER

    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=background,
        fg=foreground,
        activebackground=hover_background,
        activeforeground=TEXT,
        disabledforeground=DISABLED_TEXT,
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=normal_border,
        highlightcolor=normal_border,
        cursor="hand2",
        font=("Segoe UI Semibold", 10),
        padx=scaled_px(parent, 15),
        pady=scaled_px(parent, 8),
    )

    def enter(_event: tk.Event[tk.Misc]) -> None:
        if str(button.cget("state")) == "normal":
            button.configure(
                bg=hover_background,
                highlightbackground=hover_border,
                highlightcolor=hover_border,
            )

    def leave(_event: tk.Event[tk.Misc]) -> None:
        if str(button.cget("state")) == "normal":
            button.configure(
                bg=background,
                highlightbackground=normal_border,
                highlightcolor=normal_border,
            )

    button.bind("<Enter>", enter)
    button.bind("<Leave>", leave)
    return button

def primary_action_button(parent: tk.Misc, text: str, command: object) -> tk.Button:
    """Use one shared visual style for spinning and mass distribution."""
    button = tk.Button(
        parent, text=text, command=command, bg=CTA_BACKGROUND, fg="#F1EEE5",
        activebackground=CTA_PRESSED, activeforeground="#F1EEE5",
        disabledforeground="#686E69", relief="flat", borderwidth=0,
        highlightthickness=1, highlightbackground=CTA_BORDER, highlightcolor=CTA_BORDER,
        cursor="hand2", font=("Segoe UI Semibold", 12), pady=scaled_px(parent, 12),
    )

    def set_hover(hovered: bool) -> None:
        if str(button.cget("state")) == "normal":
            border = CTA_HOVER_BORDER if hovered else CTA_BORDER
            button.configure(bg=CTA_HOVER if hovered else CTA_BACKGROUND,
                             highlightbackground=border, highlightcolor=border)

    button.bind("<Enter>", lambda _event: set_hover(True))
    button.bind("<Leave>", lambda _event: set_hover(False))
    return button


class CopyNickname(tk.Canvas):
    """Compact rounded nickname chip with fixed-space, fading copy feedback."""

    FADE_STEPS = 18
    FADE_INTERVAL_MS = 65

    def __init__(self, parent: tk.Misc, nickname: str, background: str = SURFACE) -> None:
        super().__init__(parent, bg=background, highlightthickness=0, borderwidth=0, takefocus=1)
        self.nickname = nickname
        self._name_font = tkfont.Font(root=self, family="Segoe UI", size=10)
        self._feedback_font = tkfont.Font(root=self, family="Segoe UI Semibold", size=8)
        self._max_width = scaled_px(parent, 360)
        self._hovered = False
        self._focused = False
        self._feedback_after_id: str | None = None
        self._feedback_width = self._feedback_font.measure("Скопировано") + scaled_px(self, 2)
        self._chip_width = 1
        self._chip_height = 1
        self._shape = self.create_polygon(0, 0, 1, 1, smooth=True, splinesteps=16, fill=NICKNAME_BACKGROUND, outline="")
        self._name_text = self.create_text(0, 0, text=nickname, font=self._name_font, fill=TEXT, anchor="nw")
        self._feedback_text = self.create_text(
            0, 0, text="Скопировано", font=self._feedback_font, fill=ACCENT,
            anchor="w", state="hidden",
        )
        self._layout()
        self.bind("<Enter>", self._pointer_move)
        self.bind("<Motion>", self._pointer_move)
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", lambda _event: self.copy())
        self.bind("<space>", lambda _event: self.copy())
        self.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.bind("<FocusOut>", lambda _event: self._set_focus(False))

    def set_max_width(self, width: int) -> None:
        if self._max_width != width:
            self._max_width = width
            self._layout()

    def _layout(self) -> None:
        pad_x, pad_y = scaled_px(self, 8), scaled_px(self, 4)
        gap = scaled_px(self, 6)
        text_width = max(scaled_px(self, 12), self._max_width - self._feedback_width - gap - 2 * pad_x)
        self.coords(self._name_text, pad_x, pad_y)
        self.itemconfigure(self._name_text, width=text_width)
        bounds = self.bbox(self._name_text)
        self._chip_width = bounds[2] - bounds[0] + 2 * pad_x
        self._chip_height = bounds[3] - bounds[1] + 2 * pad_y
        width, height = self._chip_width, self._chip_height
        radius = min(scaled_px(self, 6), width // 2, height // 2)
        self.coords(self._shape,
                    radius, 0, width - radius, 0, width, 0, width, radius,
                    width, height - radius, width, height, width - radius, height,
                    radius, height, 0, height, 0, height - radius, 0, radius, 0, 0)
        self.coords(self._feedback_text, width + gap, height // 2)
        self.configure(width=width + gap + self._feedback_width, height=height)

    def _pointer_move(self, event: tk.Event) -> None:
        self._set_hover(0 <= event.x < self._chip_width and 0 <= event.y < self._chip_height)

    def _set_hover(self, hovered: bool) -> None:
        if self._hovered != hovered:
            self._hovered = hovered
            self.configure(cursor="hand2" if hovered else "")
            self._update_chip_color()

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self._update_chip_color()

    def _update_chip_color(self) -> None:
        self.itemconfigure(self._shape, fill=NICKNAME_HOVER if self._hovered or self._focused else NICKNAME_BACKGROUND)

    def _click(self, event: tk.Event) -> str | None:
        if 0 <= event.x < self._chip_width and 0 <= event.y < self._chip_height:
            return self.copy()
        return None

    def copy(self) -> str:
        if not self.winfo_exists():
            return "break"
        try:
            self.clipboard_clear()
            self.clipboard_append(self.nickname)
        except tk.TclError:
            return "break"
        self._cancel_feedback()
        self.itemconfigure(self._feedback_text, state="normal", fill=ACCENT)
        self._fade_feedback(0)
        return "break"

    def _fade_feedback(self, step: int) -> None:
        self._feedback_after_id = None
        if step >= self.FADE_STEPS:
            self.itemconfigure(self._feedback_text, state="hidden")
            return
        background = str(self.cget("bg"))
        start = self.winfo_rgb(ACCENT)
        end = self.winfo_rgb(background)
        amount = step / self.FADE_STEPS
        color = "#" + "".join(f"{round((a + (b - a) * amount) / 257):02X}" for a, b in zip(start, end))
        self.itemconfigure(self._feedback_text, fill=color)
        self._feedback_after_id = self.after(self.FADE_INTERVAL_MS, self._fade_feedback, step + 1)

    def _cancel_feedback(self) -> None:
        if self._feedback_after_id is not None:
            self.after_cancel(self._feedback_after_id)
            self._feedback_after_id = None

    def destroy(self) -> None:
        self._cancel_feedback()
        super().destroy()


class WinnerNicknameCopy:
    """Add per-name copying to a label without replacing or relaying it out."""

    FADE_STEPS = 18
    FADE_INTERVAL_MS = 55

    def __init__(self, label: tk.Label, caption: tk.Label) -> None:
        self.label = label
        self.caption = caption
        # Tk child labels cannot be translucent. A borderless, non-focusable
        # owned overlay lets the backing and text fade together over the nick.
        self._feedback_window = tk.Toplevel(label, background=SURFACE_LIGHT, takefocus=0)
        self._feedback_window.withdraw()
        self._feedback_window.overrideredirect(True)
        self._feedback_window.transient(label.winfo_toplevel())
        self._feedback_window.attributes("-alpha", 0.0)
        self._feedback_opacity = 1.0
        self.feedback = tk.Label(
            self._feedback_window, text="Скопировано", bg=SURFACE_LIGHT, fg=ACCENT,
            font=("Segoe UI Semibold", 8), borderwidth=0,
            padx=scaled_px(label, 6), pady=scaled_px(label, 3),
        )
        self.feedback.pack()
        self.feedback.bind("<Button-1>", self._feedback_click)
        # An unmanaged canvas uses the same native Tk text layout as the label,
        # including word wrapping. It is never displayed or geometry-managed.
        self._mirror = tk.Canvas(label, highlightthickness=0, borderwidth=0)
        self._text_item = self._mirror.create_text(0, 0, anchor="nw")
        self._signature = None
        self._font_spec = None
        self._font = None
        self._ranges: list[tuple[int, int, str]] = []
        self._lines: list[tuple[int, int, float, float]] = []
        self._origin = (0, 0)
        self._line_height = 1
        self._feedback_after_id: str | None = None
        self._cursor = ""
        for sequence in ("<Enter>", "<Motion>"):
            label.bind(sequence, self._pointer_move, add="+")
        label.bind("<Leave>", lambda _event: self._set_cursor(""), add="+")
        label.bind("<Button-1>", self._click, add="+")
        label.bind("<Destroy>", self._destroy, add="+")

    def refresh(self) -> None:
        self._signature = None
        self._cancel_feedback()
        self._feedback_window.withdraw()
        self._set_cursor("")

    def _ensure_layout(self) -> None:
        text = str(self.label.cget("text"))
        font_spec = str(self.label.cget("font"))
        wrap = self.label.winfo_pixels(self.label.cget("wraplength"))
        justify = str(self.label.cget("justify"))
        width, height = self.label.winfo_width(), self.label.winfo_height()
        signature = (text, font_spec, wrap, justify, width, height)
        if signature == self._signature:
            return
        self._signature = signature
        self._ranges = []
        position = 0
        for name in text.split(" | ") if text else []:
            length = int(self.label.tk.call("string", "length", name))
            self._ranges.append((position, position + length, name))
            position += length + 3
        self._mirror.itemconfigure(self._text_item, text=text, font=font_spec, width=wrap, justify=justify)
        self._lines = []
        bounds = self._mirror.bbox(self._text_item)
        if not text or bounds is None:
            return
        if font_spec != self._font_spec:
            self._font_spec = font_spec
            self._font = tkfont.Font(root=self.label, font=font_spec)
        # Canvas text bounds include a one-pixel horizontal drawing margin.
        layout_width, layout_height = bounds[2] - bounds[0] - 2, bounds[3] - bounds[1]
        self._origin = ((width - layout_width) // 2, (height - layout_height) // 2)
        self._line_height = self._font.metrics("linespace")
        for index in range((layout_height + self._line_height - 1) // self._line_height):
            y = index * self._line_height + self._line_height // 2
            start = self._mirror.index(self._text_item, f"@-100000,{y}")
            end = self._mirror.index(self._text_item, f"@100000,{y}")
            line = str(self.label.tk.call("string", "range", text, start, end - 1)).rstrip()
            line_width = self._font.measure(line)
            left = (layout_width - line_width) / 2 if justify == "center" else (
                layout_width - line_width if justify == "right" else 0
            )
            self._lines.append((start, end, left, left + line_width))

    def nickname_at(self, x: int, y: int) -> str | None:
        if not (0 <= x < self.label.winfo_width() and 0 <= y < self.label.winfo_height()):
            return None
        self._ensure_layout()
        x, y = x - self._origin[0], y - self._origin[1]
        line_index = y // self._line_height
        if not 0 <= line_index < len(self._lines):
            return None
        _start, _end, left, right = self._lines[line_index]
        if not left <= x < right:
            return None
        character = self._mirror.index(self._text_item, f"@{x},{y}")
        return next((name for start, end, name in self._ranges if start <= character < end), None)

    def _set_cursor(self, cursor: str) -> None:
        if cursor != self._cursor:
            self._cursor = cursor
            self.label.configure(cursor=cursor)

    def _pointer_move(self, event: tk.Event) -> None:
        self._set_cursor("hand2" if self.nickname_at(event.x, event.y) is not None else "")

    def _click(self, event: tk.Event) -> str | None:
        return self._copy_at(event.x, event.y)

    def _feedback_click(self, event: tk.Event) -> str | None:
        # The overlay must not swallow a repeat click on the nickname below it.
        x = self.feedback.winfo_rootx() + event.x - self.label.winfo_rootx()
        y = self.feedback.winfo_rooty() + event.y - self.label.winfo_rooty()
        return self._copy_at(x, y)

    def _copy_at(self, x: int, y: int) -> str | None:
        name = self.nickname_at(x, y)
        if name is None:
            return None
        try:
            self.label.clipboard_clear()
            self.label.clipboard_append(name)
        except tk.TclError:
            return "break"
        self._cancel_feedback()
        self.feedback.configure(fg=ACCENT, bg=SURFACE_LIGHT)
        parent = self.caption.master
        width, height = self.feedback.winfo_reqwidth(), self.feedback.winfo_reqheight()
        # Anchor the lower-left corner at the click, keeping the backing in the card.
        left = self.label.winfo_rootx() - parent.winfo_rootx() + x
        top = self.label.winfo_rooty() - parent.winfo_rooty() + y - height
        left = max(0, min(left, parent.winfo_width() - width))
        top = max(0, min(top, parent.winfo_height() - height))
        self._feedback_window.geometry(
            f"{width}x{height}{parent.winfo_rootx() + left:+d}{parent.winfo_rooty() + top:+d}"
        )
        self._feedback_opacity = float(self.label.winfo_toplevel().attributes("-alpha"))
        self._feedback_window.attributes("-alpha", self._feedback_opacity)
        self._feedback_window.deiconify()
        self._feedback_window.lift()
        self._fade_feedback(0)
        return "break"

    def _fade_feedback(self, step: int) -> None:
        self._feedback_after_id = None
        if step >= self.FADE_STEPS:
            self._feedback_window.withdraw()
            return
        self._feedback_window.attributes("-alpha", self._feedback_opacity * (1 - step / self.FADE_STEPS))
        self._feedback_after_id = self.feedback.after(self.FADE_INTERVAL_MS, self._fade_feedback, step + 1)

    def _cancel_feedback(self) -> None:
        if self._feedback_after_id is not None:
            self.feedback.after_cancel(self._feedback_after_id)
            self._feedback_after_id = None

    def _destroy(self, _event: tk.Event) -> None:
        self._cancel_feedback()


class StyledCheckbutton(tk.Canvas):
    SIZE = 30

    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.BooleanVar,
        background: str = SURFACE,
    ) -> None:
        self.ui_scale = widget_ui_scale(parent)
        self.size = max(16, round(self.SIZE * self.ui_scale))
        super().__init__(
            parent,
            width=self.size,
            height=self.size,
            bg=background,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.variable = variable
        self.hovered = False
        self._trace_id = variable.trace_add("write", self._on_value_changed)
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._redraw)
        self.bind("<FocusOut>", self._redraw)
        self.bind("<Destroy>", self._remove_trace, add="+")
        self._redraw()

    def _toggle(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if str(self.cget("state")) != "disabled":
            self.variable.set(not self.variable.get())
        return "break"

    def _on_value_changed(self, *_args: object) -> None:
        self._redraw()

    def _enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        px = lambda value: max(1, round(value * self.ui_scale))
        self.delete("all")
        selected = self.variable.get()
        focused = self.focus_get() is self
        if selected:
            fill = BRAND_GREEN
            outline = "#A4ACA6" if self.hovered or focused else BRAND_GREEN_LIGHT
        else:
            fill = "#202521" if self.hovered else "#171A18"
            outline = "#A4ACA6" if self.hovered or focused else "#626A64"
        self.create_rectangle(
            px(3),
            px(3),
            self.size - px(3),
            self.size - px(3),
            fill=fill,
            outline=outline,
            width=px(2),
        )
        if selected:
            self.create_line(
                px(8),
                px(15),
                px(13),
                px(20),
                px(22),
                px(10),
                fill="#E3E6E3",
                width=px(3),
                capstyle="round",
                joinstyle="round",
            )

    def _remove_trace(self, _event: tk.Event[tk.Misc]) -> None:
        try:
            self.variable.trace_remove("write", self._trace_id)
        except tk.TclError:
            pass


class StyledDeleteButton(tk.Canvas):
    SIZE = 30

    def __init__(
        self,
        parent: tk.Misc,
        command: object,
        background: str = SURFACE,
    ) -> None:
        self.ui_scale = widget_ui_scale(parent)
        self.size = max(16, round(self.SIZE * self.ui_scale))
        super().__init__(
            parent,
            width=self.size,
            height=self.size,
            bg=background,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.base_background = background
        self.command = command
        self.hovered = False
        self.bind("<Button-1>", self._activate)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._redraw)
        self.bind("<FocusOut>", self._redraw)
        self._redraw()

    def _activate(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if str(self.cget("state")) != "disabled" and callable(self.command):
            self.command()
        return "break"

    def _enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        px = lambda value: max(1, round(value * self.ui_scale))
        self.delete("all")
        focused = self.focus_get() is self
        active = self.hovered or focused
        fill = "#302424" if active else self.base_background
        outline = "#60403E" if active else self.base_background
        cross = "#A87872" if active else "#656B66"
        self.create_rectangle(
            px(3),
            px(3),
            self.size - px(3),
            self.size - px(3),
            fill=fill,
            outline=outline,
            width=px(1),
        )
        cross_width = px(2 if active else 1)
        self.create_line(
            px(10),
            px(10),
            px(20),
            px(20),
            fill=cross,
            width=cross_width,
            capstyle="round",
        )
        self.create_line(
            px(20),
            px(10),
            px(10),
            px(20),
            fill=cross,
            width=cross_width,
            capstyle="round",
        )


class PrizeImageCard(tk.Canvas):
    EMPTY_WIDTH = 180
    EMPTY_HEIGHT = 68
    BORDER_PADDING = 2
    MAX_CARD_WIDTH = 500
    MAX_IMAGE_WIDTH = MAX_CARD_WIDTH - BORDER_PADDING * 2
    MAX_IMAGE_HEIGHT = 64

    def __init__(
        self,
        parent: tk.Misc,
        max_card_width: int | None = None,
        on_clear: Callable[[], None] | None = None,
    ) -> None:
        self.ui_scale = widget_ui_scale(parent)
        logical_max_width = max_card_width or self.MAX_CARD_WIDTH
        self.max_image_width = logical_max_width - self.BORDER_PADDING * 2
        self.on_clear = on_clear
        self.empty_width = max(90, round(self.EMPTY_WIDTH * self.ui_scale))
        self.empty_height = max(32, round(self.EMPTY_HEIGHT * self.ui_scale))
        self.border_padding = max(1, round(self.BORDER_PADDING * self.ui_scale))
        super().__init__(
            parent,
            width=self.empty_width,
            height=self.empty_height,
            bg=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self.image: Image.Image | None = None
        self.normal_photo: ImageTk.PhotoImage | None = None
        self.dimmed_photo: ImageTk.PhotoImage | None = None
        self.hovered = False
        self.card_width = self.empty_width
        self.card_height = self.empty_height
        self.locked = False
        self.bind("<Button-1>", self._activate)
        self.bind("<Return>", self._activate)
        self.bind("<space>", self._activate)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._redraw)
        self.bind("<FocusOut>", self._redraw)
        self._redraw()

    def _activate(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self.locked:
            return "break"
        if self.image is not None:
            self.clear()
            return "break"
        try:
            image = clipboard_image()
        except OcrError as error:
            messagebox.showwarning(
                APP_NAME,
                str(error),
                parent=self.winfo_toplevel(),
            )
            return "break"
        self.set_image(image)
        return "break"

    def set_image(self, image: Image.Image) -> None:
        self.image = image.copy()
        source = self.image.convert("RGBA")
        source.thumbnail(
            (
                self.max_image_width,
                self.EMPTY_HEIGHT - self.BORDER_PADDING * 2,
            ),
            Image.Resampling.LANCZOS,
        )
        if not math.isclose(self.ui_scale, 1.0):
            source = source.resize(
                (
                    max(1, round(source.width * self.ui_scale)),
                    max(1, round(source.height * self.ui_scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        preview = Image.new(
            "RGBA",
            source.size,
            ImageColor.getrgb(SURFACE) + (255,),
        )
        preview.alpha_composite(source, (0, 0))
        normal = preview.convert("RGB")
        dim_layer = Image.new("RGB", normal.size, WINNER_BACKGROUND)
        dimmed = Image.blend(normal, dim_layer, 0.58)
        self.normal_photo = ImageTk.PhotoImage(normal)
        self.dimmed_photo = ImageTk.PhotoImage(dimmed)
        self.card_width = source.width + self.border_padding * 2
        self.card_height = self.empty_height
        self.configure(width=self.card_width, height=self.card_height)
        self._redraw()

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        self.configure(cursor="arrow" if locked else "hand2")

    def clear(self) -> None:
        self.image = None
        self.normal_photo = None
        self.dimmed_photo = None
        self.card_width = self.empty_width
        self.card_height = self.empty_height
        self.configure(width=self.card_width, height=self.card_height)
        self._redraw()
        if self.on_clear is not None:
            self.on_clear()

    def _enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = True
        self._redraw()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        px = lambda value: max(1, round(value * self.ui_scale))
        self.delete("all")
        focused = self.focus_get() is self
        center_x = self.card_width // 2
        center_y = self.card_height // 2
        border = BORDER_LIGHT if self.hovered or focused else BORDER

        self.create_rectangle(
            px(1),
            px(1),
            self.card_width - px(1),
            self.card_height - px(1),
            fill=SURFACE,
            outline=border,
            width=px(2),
        )
        if self.image is None:
            plus_color = ACCENT_HOVER if self.hovered or focused else MUTED
            self.create_line(
                center_x - px(13),
                center_y,
                center_x + px(13),
                center_y,
                fill=plus_color,
                width=px(3),
                capstyle="round",
            )
            self.create_line(
                center_x,
                center_y - px(13),
                center_x,
                center_y + px(13),
                fill=plus_color,
                width=px(3),
                capstyle="round",
            )
            return

        photo = self.dimmed_photo if self.hovered else self.normal_photo
        if photo is not None:
            self.create_image(center_x, center_y, image=photo)
        self.create_rectangle(
            px(1),
            px(1),
            self.card_width - px(1),
            self.card_height - px(1),
            outline=border,
            width=px(2),
        )
        if self.hovered or focused:
            cross_size = min(
                px(14),
                max(px(7), min(self.card_width, self.card_height) // 4),
            )
            self.create_line(
                center_x - cross_size,
                center_y - cross_size,
                center_x + cross_size,
                center_y + cross_size,
                fill=TEXT_BRIGHT,
                width=px(4),
                capstyle="round",
            )
            self.create_line(
                center_x + cross_size,
                center_y - cross_size,
                center_x - cross_size,
                center_y + cross_size,
                fill=TEXT_BRIGHT,
                width=px(4),
                capstyle="round",
            )


class PrizeQuantityControl(tk.Frame):
    MINIMUM = 1
    MAXIMUM = 9999
    WIDTH = 36
    HEIGHT = PrizeImageCard.EMPTY_HEIGHT

    def __init__(self, parent: tk.Misc, value: int = 1) -> None:
        self.ui_scale = widget_ui_scale(parent)
        self.control_width = max(32, round(self.WIDTH * self.ui_scale))
        self.control_height = max(32, round(self.HEIGHT * self.ui_scale))
        super().__init__(
            parent,
            width=self.control_width,
            height=self.control_height,
            bg=BACKGROUND,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        button_height = max(8, round(22 * self.ui_scale))
        self.grid_rowconfigure(0, minsize=button_height)
        self.grid_rowconfigure(
            1,
            weight=1,
            minsize=max(12, self.control_height - button_height * 2),
        )
        self.grid_rowconfigure(2, minsize=button_height)
        self.locked = False
        self.quantity_var = tk.StringVar(value=str(value))
        validator = (self.register(self._validate), "%P")

        self.plus_button = self._step_button("▲", 1, 0)
        self.entry = tk.Entry(
            self,
            textvariable=self.quantity_var,
            justify="center",
            bg=INPUT_BACKGROUND,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=INPUT_BACKGROUND,
            disabledforeground=TEXT,
            relief="flat",
            font=("Segoe UI Semibold", 11),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER_LIGHT,
            validate="key",
            validatecommand=validator,
        )
        enable_entry_shortcuts(self.entry)
        self.entry.grid(row=1, column=0, sticky="nsew")
        self.minus_button = self._step_button("▼", -1, 2)

        self.entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")
        self.entry.bind("<Return>", self._commit_and_release_focus, add="+")
        self.entry.bind("<KP_Enter>", self._commit_and_release_focus, add="+")
        self.entry.bind("<Up>", lambda _event: self._adjust(1), add="+")
        self.entry.bind("<Down>", lambda _event: self._adjust(-1), add="+")
        self.quantity_var.trace_add("write", self._update_step_button_states)
        self.set_value(value)

    def _step_button(self, text: str, delta: int, row: int) -> tk.Button:
        button = tk.Button(
            self,
            text=text,
            command=lambda: self._adjust(delta),
            bg=SURFACE_LIGHT,
            fg=TEXT,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_BRIGHT,
            disabledforeground=DISABLED_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BUTTON_BORDER,
            highlightcolor=BUTTON_BORDER,
            cursor="hand2",
            font=("Segoe UI Symbol", 8),
            padx=0,
            pady=0,
        )
        button.grid(row=row, column=0, sticky="nsew")
        button.bind("<Enter>", self._on_step_button_enter, add="+")
        button.bind("<Leave>", self._on_step_button_leave, add="+")
        return button

    def _on_step_button_enter(self, event: tk.Event[tk.Misc]) -> None:
        button = event.widget
        if isinstance(button, tk.Button) and str(button.cget("state")) == "normal":
            button.configure(
                bg=BUTTON_HOVER,
                highlightbackground=BUTTON_HOVER_BORDER,
                highlightcolor=BUTTON_HOVER_BORDER,
            )

    def _on_step_button_leave(self, event: tk.Event[tk.Misc]) -> None:
        button = event.widget
        if isinstance(button, tk.Button) and str(button.cget("state")) == "normal":
            button.configure(
                bg=SURFACE_LIGHT,
                highlightbackground=BUTTON_BORDER,
                highlightcolor=BUTTON_BORDER,
            )

    def _update_step_button_states(self, *_args: object) -> None:
        try:
            value = int(self.quantity_var.get())
        except ValueError:
            value = self.MINIMUM
        self.plus_button.configure(state="disabled" if self.locked else "normal")
        self.minus_button.configure(
            state="disabled" if self.locked or value <= self.MINIMUM else "normal"
        )

    def _validate(self, proposed: str) -> bool:
        return proposed == "" or (
            proposed.isdigit() and len(proposed) <= len(str(self.MAXIMUM))
        )

    def value(self) -> int:
        try:
            value = int(self.quantity_var.get())
        except ValueError:
            value = self.MINIMUM
        value = min(self.MAXIMUM, max(self.MINIMUM, value))
        normalized = str(value)
        if self.quantity_var.get() != normalized:
            self.quantity_var.set(normalized)
        return value

    def set_value(self, value: int) -> None:
        normalized = min(self.MAXIMUM, max(self.MINIMUM, int(value)))
        self.quantity_var.set(str(normalized))

    def _adjust(self, delta: int) -> str:
        if not self.locked:
            self.set_value(self.value() + delta)
        return "break"

    def _on_focus_in(self, _event: tk.Event[tk.Misc]) -> None:
        self.entry.configure(
            highlightbackground=BORDER_LIGHT,
            highlightcolor=BORDER_LIGHT,
        )

    def _on_focus_out(self, _event: tk.Event[tk.Misc]) -> None:
        self.value()
        self.entry.configure(
            highlightbackground=BORDER,
            highlightcolor=BORDER_LIGHT,
        )

    def _commit_and_release_focus(
        self, _event: tk.Event[tk.Misc]
    ) -> str:
        self.value()
        self.winfo_toplevel().focus_set()
        return "break"

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        state = "disabled" if locked else "normal"
        cursor = "arrow" if locked else "hand2"
        self.entry.configure(state=state)
        self.minus_button.configure(cursor=cursor)
        self.plus_button.configure(cursor=cursor)
        self._update_step_button_states()
