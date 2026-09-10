"""Filesystem, Windows integration, scaling, and Tk clipboard helpers."""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageColor, ImageTk

from .theme import BACKGROUND


def resource_path(*parts: str) -> Path:
    """Resolve a resource both from source and from a PyInstaller bundle."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    base = (
        Path(bundle_root)
        if bundle_root
        else Path(__file__).resolve().parent.parent
    )
    return base.joinpath(*parts)


def application_directory() -> Path:
    """Return the folder containing app.py or the packaged executable."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def widget_ui_scale(widget: tk.Misc) -> float:
    try:
        return float(getattr(widget.winfo_toplevel(), "ui_scale", 1.0))
    except (AttributeError, tk.TclError, TypeError, ValueError):
        return 1.0


def scaled_px(widget: tk.Misc, value: float, minimum: int = 1) -> int:
    return max(minimum, round(value * widget_ui_scale(widget)))


def monitor_size_for_window(window: tk.Misc) -> tuple[int, int]:
    """Return the pixel size of the monitor containing a Tk window."""

    if os.name != "nt":
        return window.winfo_screenwidth(), window.winfo_screenheight()
    try:
        from ctypes import (
            POINTER,
            Structure,
            byref,
            c_int,
            c_ulong,
            c_void_p,
            sizeof,
            windll,
        )
        from ctypes.wintypes import RECT

        class MonitorInfo(Structure):
            _fields_ = (
                ("cbSize", c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", c_ulong),
            )

        window.update_idletasks()
        windll.user32.GetParent.argtypes = (c_void_p,)
        windll.user32.GetParent.restype = c_void_p
        windll.user32.MonitorFromWindow.argtypes = (c_void_p, c_ulong)
        windll.user32.MonitorFromWindow.restype = c_void_p
        windll.user32.GetMonitorInfoW.argtypes = (
            c_void_p,
            POINTER(MonitorInfo),
        )
        windll.user32.GetMonitorInfoW.restype = c_int
        client_handle = window.winfo_id()
        native_handle = windll.user32.GetParent(client_handle) or client_handle
        monitor = windll.user32.MonitorFromWindow(c_void_p(native_handle), 2)
        if not monitor:
            raise OSError("MonitorFromWindow failed")
        info = MonitorInfo()
        info.cbSize = sizeof(MonitorInfo)
        if not windll.user32.GetMonitorInfoW(c_void_p(monitor), byref(info)):
            raise OSError("GetMonitorInfoW failed")
        return (
            int(info.rcMonitor.right - info.rcMonitor.left),
            int(info.rcMonitor.bottom - info.rcMonitor.top),
        )
    except (AttributeError, OSError, tk.TclError, TypeError, ValueError):
        return window.winfo_screenwidth(), window.winfo_screenheight()


def apply_window_icon(window: tk.Misc, default: bool = False) -> None:
    """Apply the guild emblem to Tk windows and the Windows taskbar."""

    try:
        window.iconbitmap(str(resource_path("imgs", "guild app icon.ico")))
    except (OSError, tk.TclError):
        pass
    try:
        with Image.open(resource_path("imgs", "guild app icon.png")) as source:
            icon = source.convert("RGBA")
        icon.thumbnail((256, 256), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(icon)
        window.iconphoto(default, photo)
        window._guild_icon_photo = photo  # type: ignore[attr-defined]
    except (OSError, ValueError, tk.TclError):
        pass


def apply_dark_title_bar(window: tk.Misc) -> None:
    """Apply a native dark Windows caption without replacing window controls."""

    if os.name != "nt":
        return
    try:
        from ctypes import byref, c_int, c_uint, c_void_p, sizeof, windll

        window.update_idletasks()
        windll.user32.GetParent.argtypes = (c_void_p,)
        windll.user32.GetParent.restype = c_void_p
        windll.dwmapi.DwmSetWindowAttribute.argtypes = (
            c_void_p,
            c_uint,
            c_void_p,
            c_uint,
        )
        windll.dwmapi.DwmSetWindowAttribute.restype = c_int
        windll.user32.SetWindowPos.argtypes = (
            c_void_p,
            c_void_p,
            c_int,
            c_int,
            c_int,
            c_int,
            c_uint,
        )
        client_handle = window.winfo_id()
        window_handle = windll.user32.GetParent(client_handle) or client_handle

        enabled = c_int(1)
        for attribute in (20, 19):
            result = windll.dwmapi.DwmSetWindowAttribute(
                window_handle,
                attribute,
                byref(enabled),
                sizeof(enabled),
            )
            if result == 0:
                break

        # Exact per-window caption colors are available only on Windows 11.
        # Windows 10 keeps the native immersive dark caption enabled above.
        if sys.getwindowsversion().build >= 22000:
            def colorref(hex_color: str) -> c_int:
                red, green, blue = ImageColor.getrgb(hex_color)
                return c_int(red | (green << 8) | (blue << 16))

            for attribute, color in (
                (35, BACKGROUND),
                (36, "#D9DDD9"),
                (34, "#383E39"),
            ):
                value = colorref(color)
                windll.dwmapi.DwmSetWindowAttribute(
                    window_handle,
                    attribute,
                    byref(value),
                    sizeof(value),
                )

        # Ask Windows to redraw the non-client area immediately.
        windll.user32.SetWindowPos(
            window_handle,
            0,
            0,
            0,
            0,
            0,
            0x0020 | 0x0001 | 0x0002 | 0x0004,
        )
    except (AttributeError, OSError, tk.TclError):
        pass


def keep_dark_title_bar(window: tk.Misc) -> None:
    """Reapply DWM caption styling after Windows remaps a native window."""

    if os.name != "nt":
        return

    pending: set[str] = set()
    state = {"destroyed": False, "refreshing": False}

    def apply_if_alive() -> None:
        if state["destroyed"] or state["refreshing"]:
            return
        try:
            if not window.winfo_exists():
                return
            state["refreshing"] = True
            apply_dark_title_bar(window)
        except tk.TclError:
            pass
        finally:
            state["refreshing"] = False

    def schedule(delay_ms: int) -> None:
        token_box: dict[str, str] = {}

        def run() -> None:
            token = token_box.get("token")
            if token is not None:
                pending.discard(token)
            apply_if_alive()

        try:
            token = window.after(delay_ms, run)
        except tk.TclError:
            return
        token_box["token"] = token
        pending.add(token)

    def refresh(event: tk.Event[tk.Misc]) -> None:
        if event.widget is not window or state["destroyed"]:
            return
        apply_if_alive()
        # DWM can finish rebuilding a restored caption after Tk's Map event.
        # Two short retries cover both the immediate and delayed restore paths.
        schedule(20)
        schedule(120)

    def cleanup(event: tk.Event[tk.Misc]) -> None:
        if event.widget is not window:
            return
        state["destroyed"] = True
        for token in tuple(pending):
            try:
                window.after_cancel(token)
            except tk.TclError:
                pass
        pending.clear()

    window.bind("<Map>", refresh, add="+")
    window.bind("<Destroy>", cleanup, add="+")


def clipboard_sequence_number() -> int:
    """Return the Windows clipboard revision without opening the clipboard."""

    if os.name != "nt":
        return 0
    try:
        from ctypes import windll

        return int(windll.user32.GetClipboardSequenceNumber())
    except (AttributeError, OSError):
        return 0


def handle_entry_shortcut(event: tk.Event[tk.Misc]) -> str | None:
    """Provide layout-independent Windows editing shortcuts for text fields."""

    entry = event.widget
    if not isinstance(entry, (tk.Entry, ttk.Entry)):
        return None

    keycode = int(getattr(event, "keycode", 0) or 0)
    keysym = str(getattr(event, "keysym", "")).casefold()
    actions = {
        "select_all": keycode == 65
        or keysym in {"a", "ф", "cyrillic_ef"},
        "copy": keycode == 67
        or keysym in {"c", "с", "cyrillic_es"},
        "paste": keycode == 86
        or keysym in {"v", "м", "cyrillic_em"},
        "cut": keycode == 88
        or keysym in {"x", "ч", "cyrillic_che"},
    }
    action = next((name for name, active in actions.items() if active), None)
    if action is None:
        return None

    editable = str(entry.cget("state")) == "normal"
    if action == "select_all":
        entry.selection_range(0, tk.END)
        entry.icursor(tk.END)
        return "break"

    try:
        selection_start = entry.index(tk.SEL_FIRST)
        selection_end = entry.index(tk.SEL_LAST)
    except tk.TclError:
        selection_start = selection_end = None

    if action in {"copy", "cut"}:
        if selection_start is not None and selection_end is not None:
            selected_text = entry.get()[selection_start:selection_end]
            entry.clipboard_clear()
            entry.clipboard_append(selected_text)
            if action == "cut" and editable:
                entry.delete(selection_start, selection_end)
        return "break"

    if not editable:
        return "break"
    try:
        clipboard_text = entry.clipboard_get()
    except tk.TclError:
        return "break"
    # Entry is single-line; normalize multiline clipboard content accordingly.
    clipboard_text = " ".join(str(clipboard_text).splitlines())
    if selection_start is not None and selection_end is not None:
        entry.delete(selection_start, selection_end)
    entry.insert(tk.INSERT, clipboard_text)
    return "break"


def enable_entry_shortcuts(entry: tk.Entry | ttk.Entry) -> None:
    entry.bind("<Control-KeyPress>", handle_entry_shortcut, add="+")


def is_foreground_window(window: tk.Misc) -> bool:
    """Check whether a Tk top-level currently owns the foreground."""

    if os.name != "nt":
        return window.focus_displayof() is not None
    try:
        from ctypes import c_void_p, windll

        windll.user32.GetParent.argtypes = (c_void_p,)
        windll.user32.GetParent.restype = c_void_p
        windll.user32.GetForegroundWindow.restype = c_void_p
        client_handle = window.winfo_id()
        window_handle = windll.user32.GetParent(client_handle) or client_handle
        return int(windll.user32.GetForegroundWindow() or 0) == int(
            window_handle
        )
    except (AttributeError, OSError, tk.TclError):
        return False
