"""Tkinter 界面基础件：配色、字体、扁平按钮、输入框、可滚动容器。

这里只做"看起来干净"的最小集合：纯色面板、细分隔线、扁平按钮，没有图片资源。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PALETTE = {
    "bg": "#f4f6fb",
    "panel": "#ffffff",
    "soft": "#f7f9fd",
    "border": "#e3e7f0",
    "border_strong": "#d3d9e8",
    "text": "#1b2130",
    "text_soft": "#4a5366",
    "muted": "#7b8497",
    "accent": "#4f7cff",
    "accent_dark": "#3a63e8",
    "accent_press": "#3155cc",
    "accent_soft": "#eef3ff",
    "danger": "#e5484d",
    "danger_soft": "#fdecec",
    "ok": "#129a5b",
    "ok_soft": "#e8f8ef",
    "star": "#f0a020",
    "star_soft": "#fff6e5",
    "group": "#7b61ff",
    "group_soft": "#f0edff",
    "white": "#ffffff",
    "row_active": "#eef3ff",
    "row_hover": "#f4f7fd",
}

FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"


def _font(size: int, weight: str = "normal", mono: bool = False):
    return ((MONO_FAMILY if mono else FAMILY), size, weight)


FONT_BODY = _font(10)
FONT_BODY_BOLD = _font(10, "bold")
FONT_SMALL = _font(9)
FONT_SMALL_BOLD = _font(9, "bold")
FONT_TITLE = _font(18, "bold")
FONT_H2 = _font(13, "bold")
FONT_H3 = _font(11, "bold")
FONT_AVATAR = _font(12, "bold")
FONT_MONO = _font(10, mono=True)
FONT_MONO_SM = _font(9, mono=True)


def refresh_fonts(root: tk.Misc) -> None:
    """按系统实际可用的字体名重建字体元组（须在 Tk 根窗口创建后调用）。"""
    global FAMILY, MONO_FAMILY
    global FONT_BODY, FONT_BODY_BOLD, FONT_SMALL, FONT_SMALL_BOLD, FONT_TITLE
    global FONT_H2, FONT_H3, FONT_AVATAR, FONT_MONO, FONT_MONO_SM

    families = set(tkfont.families(root))
    for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI"):
        if candidate in families:
            FAMILY = candidate
            break
    for candidate in ("Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono", "Courier New"):
        if candidate in families:
            MONO_FAMILY = candidate
            break

    FONT_BODY = _font(10)
    FONT_BODY_BOLD = _font(10, "bold")
    FONT_SMALL = _font(9)
    FONT_SMALL_BOLD = _font(9, "bold")
    FONT_TITLE = _font(18, "bold")
    FONT_H2 = _font(13, "bold")
    FONT_H3 = _font(11, "bold")
    FONT_AVATAR = _font(12, "bold")
    FONT_MONO = _font(10, mono=True)
    FONT_MONO_SM = _font(9, mono=True)


def init_style(root: tk.Misc) -> None:
    """统一 ttk 样式（主要用于 Combobox）与 Tk 全局选项。"""
    refresh_fonts(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Pm.TCombobox",
        fieldbackground=PALETTE["panel"],
        background=PALETTE["panel"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border_strong"],
        lightcolor=PALETTE["border_strong"],
        darkcolor=PALETTE["border_strong"],
        arrowcolor=PALETTE["text_soft"],
        padding=4,
    )
    style.map(
        "Pm.TCombobox",
        fieldbackground=[("readonly", PALETTE["panel"])],
        selectbackground=[("readonly", PALETTE["panel"])],
        foreground=[("readonly", PALETTE["text"])],
    )
    root.option_add("*TCombobox*Listbox.background", PALETTE["panel"])
    root.option_add("*TCombobox*Listbox.foreground", PALETTE["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", PALETTE["accent_soft"])
    root.option_add("*TCombobox*Listbox.selectForeground", PALETTE["text"])
    root.option_add("*TCombobox*Listbox.font", FONT_BODY)


def widget_bg(widget: tk.Misc, default: str = PALETTE["panel"]) -> str:
    try:
        return widget.cget("bg")  # type: ignore[attr-defined]
    except (tk.TclError, AttributeError):
        return default


# --------------------------------------------------------------------------- #
# 按钮
# --------------------------------------------------------------------------- #
_SCHEMES = {
    "primary": {
        "bg": PALETTE["accent"],
        "fg": "#ffffff",
        "hover": PALETTE["accent_dark"],
        "ring": None,
    },
    "secondary": {
        "bg": PALETTE["panel"],
        "fg": PALETTE["text"],
        "hover": "#eef2fb",
        "ring": PALETTE["border_strong"],
    },
    "soft": {
        "bg": PALETTE["soft"],
        "fg": PALETTE["text"],
        "hover": "#e9eef8",
        "ring": PALETTE["border"],
    },
    "ghost": {
        "bg": "inherit",
        "fg": PALETTE["text_soft"],
        "hover": "#edf1f9",
        "ring": None,
    },
    "danger": {
        "bg": PALETTE["panel"],
        "fg": PALETTE["danger"],
        "hover": PALETTE["danger_soft"],
        "ring": "#f0c4c5",
    },
}


class Button(tk.Button):
    """扁平风格按钮；``kind`` 决定配色。"""

    def __init__(
        self,
        master: tk.Misc,
        text: str = "",
        command=None,
        *,
        kind: str = "secondary",
        font=None,
        padx: int = 12,
        pady: int = 4,
        bg: str | None = None,
        **kwargs,
    ) -> None:
        scheme = _SCHEMES.get(kind, _SCHEMES["secondary"])
        parent_bg = widget_bg(master)
        normal_bg = parent_bg if scheme["bg"] == "inherit" else scheme["bg"]
        ring = scheme["ring"]
        super().__init__(
            master,
            text=text,
            command=command,
            font=font or FONT_BODY,
            bg=normal_bg,
            fg=scheme["fg"],
            activebackground=scheme["hover"],
            activeforeground=scheme["fg"],
            disabledforeground=PALETTE["muted"],
            relief="flat",
            bd=0,
            highlightthickness=1 if ring else 0,
            highlightbackground=ring or normal_bg,
            highlightcolor=ring or normal_bg,
            padx=padx,
            pady=pady,
            cursor="hand2",
            takefocus=0,
            **kwargs,
        )
        self._normal_bg = normal_bg
        self._hover_bg = scheme["hover"]
        self._ring = ring
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _is_enabled(self) -> bool:
        return str(self.cget("state")) != "disabled"

    def _on_enter(self, _event) -> None:
        if self._is_enabled():
            self.configure(bg=self._hover_bg)
            if self._ring:
                self.configure(highlightbackground=PALETTE["accent"])

    def _on_leave(self, _event) -> None:
        self.configure(bg=self._normal_bg)
        if self._ring:
            self.configure(highlightbackground=self._ring)

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.configure(state="normal", bg=self._normal_bg)
        else:
            self.configure(state="disabled", bg=PALETTE["soft"])


# --------------------------------------------------------------------------- #
# 文本 / 标签辅助
# --------------------------------------------------------------------------- #
def chip(master: tk.Misc, text: str, kind: str = "neutral", **kwargs) -> tk.Label:
    colors = {
        "neutral": (PALETTE["soft"], PALETTE["text_soft"]),
        "accent": (PALETTE["accent_soft"], PALETTE["accent_dark"]),
        "star": (PALETTE["star_soft"], "#a86d00"),
        "ok": (PALETTE["ok_soft"], PALETTE["ok"]),
        "danger": (PALETTE["danger_soft"], PALETTE["danger"]),
    }
    bg, fg = colors.get(kind, colors["neutral"])
    return tk.Label(
        master, text=text, bg=bg, fg=fg, font=FONT_SMALL, padx=8, pady=1, **kwargs
    )


def hline(master: tk.Misc, color: str | None = None, height: int = 1) -> tk.Frame:
    frame = tk.Frame(master, bg=color or PALETTE["border"], height=height)
    return frame


def vline(master: tk.Misc, color: str | None = None, width: int = 1) -> tk.Frame:
    return tk.Frame(master, bg=color or PALETTE["border"], width=width)


def section_title(master: tk.Misc, text: str) -> tk.Label:
    return tk.Label(
        master, text=text, bg=widget_bg(master), fg=PALETTE["muted"], font=FONT_SMALL_BOLD
    )


def entry(
    master: tk.Misc,
    textvariable: tk.StringVar | None = None,
    *,
    width: int = 24,
    show: str | None = None,
    font=None,
    justify: str = "left",
) -> tk.Entry:
    return tk.Entry(
        master,
        textvariable=textvariable,
        width=width,
        show=show or "",
        font=font or FONT_BODY,
        relief="flat",
        bd=0,
        bg=PALETTE["panel"],
        fg=PALETTE["text"],
        insertbackground=PALETTE["accent"],
        disabledbackground=PALETTE["soft"],
        disabledforeground=PALETTE["muted"],
        highlightthickness=1,
        highlightbackground=PALETTE["border_strong"],
        highlightcolor=PALETTE["accent"],
        justify=justify,
    )


def text_area(master: tk.Misc, height: int = 3, width: int = 30) -> tk.Text:
    return tk.Text(
        master,
        height=height,
        width=width,
        font=FONT_BODY,
        relief="flat",
        bd=0,
        wrap="word",
        bg=PALETTE["panel"],
        fg=PALETTE["text"],
        insertbackground=PALETTE["accent"],
        highlightthickness=1,
        highlightbackground=PALETTE["border_strong"],
        highlightcolor=PALETTE["accent"],
        padx=8,
        pady=6,
    )


def checkbutton(
    master: tk.Misc, text: str, variable: tk.BooleanVar, command=None
) -> tk.Checkbutton:
    return tk.Checkbutton(
        master,
        text=text,
        variable=variable,
        command=command,
        bg=widget_bg(master),
        fg=PALETTE["text_soft"],
        activebackground=widget_bg(master),
        activeforeground=PALETTE["text"],
        selectcolor=PALETTE["panel"],
        font=FONT_BODY,
        bd=0,
        highlightthickness=0,
        cursor="hand2",
    )


class PlaceholderEntry(tk.Entry):
    """带灰色占位文字的输入框。"""

    def __init__(self, master: tk.Misc, placeholder: str, textvariable=None, **kwargs) -> None:
        kwargs.setdefault("font", FONT_BODY)
        super().__init__(
            master,
            textvariable=textvariable,
            relief="flat",
            bd=0,
            bg=PALETTE["soft"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["accent"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            **kwargs,
        )
        self._placeholder = placeholder
        self._showing_placeholder = False
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        if not self.get():
            self._showing_placeholder = True
            self.configure(fg=PALETTE["muted"])
            self.insert(0, self._placeholder)

    def _on_focus_in(self, _event) -> None:
        if self._showing_placeholder:
            self.delete(0, "end")
            self.configure(fg=PALETTE["text"])
            self._showing_placeholder = False

    def _on_focus_out(self, _event) -> None:
        if not self.get():
            self._show_placeholder()

    def value(self) -> str:
        text = self.get()
        if self._showing_placeholder and text == self._placeholder:
            return ""
        if text and text != self._placeholder:
            self._showing_placeholder = False
        return text

    def clear(self) -> None:
        self._showing_placeholder = False
        self.delete(0, "end")
        self.configure(fg=PALETTE["text"])
        self._show_placeholder()


# --------------------------------------------------------------------------- #
# 可滚动容器
# --------------------------------------------------------------------------- #
class ScrollFrame(tk.Frame):
    """Canvas + 内嵌 Frame 的滚动容器；内容超出高度时才显示滚动条。"""

    def __init__(self, master: tk.Misc, bg: str | None = None) -> None:
        self._bg = bg or widget_bg(master)
        super().__init__(master, bg=self._bg)
        self.canvas = tk.Canvas(self, bg=self._bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            width=11,
            bg=PALETTE["soft"],
            troughcolor=PALETTE["bg"],
            activebackground=PALETTE["border_strong"],
            bd=0,
            relief="flat",
            highlightthickness=0,
        )
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.inner = tk.Frame(self.canvas, bg=self._bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._vsb_visible = False

    # ---- 内部事件
    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_scrollbar()

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync_scrollbar()

    def _on_yscroll(self, first: str, last: str) -> None:
        self.vsb.set(first, last)

    def _sync_scrollbar(self) -> None:
        needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1
        if needed and not self._vsb_visible:
            self.vsb.pack(side="right", fill="y")
            self._vsb_visible = True
        elif not needed and self._vsb_visible:
            self.vsb.pack_forget()
            self._vsb_visible = False

    # ---- 外部接口
    def scroll(self, delta: int) -> None:
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height() + 1:
            return
        step = -3 if delta > 0 else 3
        self.canvas.yview_scroll(step, "units")

    def reset_scroll(self) -> None:
        self.canvas.yview_moveto(0)

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()


def center_window(window: tk.Misc, width: int, height: int, parent: tk.Misc | None = None) -> None:
    window.update_idletasks()
    if parent is not None and parent.winfo_exists():
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        x = parent_x + max(0, (parent_w - width) // 2)
        y = parent_y + max(0, (parent_h - height) // 3)
    else:
        x = (window.winfo_screenwidth() - width) // 2
        y = (window.winfo_screenheight() - height) // 3
    window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
