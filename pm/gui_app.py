"""桌面客户端主程序：解锁界面与主界面（Tkinter）。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
import tkinter as tk
import webbrowser
from collections import Counter
from pathlib import Path
from tkinter import filedialog

from . import __version__
from . import store
from . import ui_kit as ui
from . import util
from .gui_dialogs import (
    AboutDialog,
    AccountEditorDialog,
    ChangeMasterDialog,
    GroupDialog,
    LinkDialog,
    ask_yes_no,
    show_error,
    show_info,
)

PALETTE = ui.PALETTE


# --------------------------------------------------------------------------- #
# 解锁 / 首次设置
# --------------------------------------------------------------------------- #
class AuthView(tk.Frame):
    def __init__(self, app: "PasswordVaultApp") -> None:
        super().__init__(app, bg=PALETTE["bg"])
        self.app = app
        self.mode = "unlock"
        self._build()

    def _build(self) -> None:
        wrap = tk.Frame(self, bg=PALETTE["bg"])
        wrap.place(relx=0.5, rely=0.43, anchor="center")

        card = tk.Frame(
            wrap,
            bg=PALETTE["panel"],
            padx=34,
            pady=28,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        card.pack()
        self.card = card

        tk.Label(
            card,
            text="P",
            bg=PALETTE["accent"],
            fg="#ffffff",
            font=(ui.FAMILY, 16, "bold"),
            width=2,
            pady=5,
        ).pack(anchor="w")

        self.title = tk.Label(card, text="", bg=PALETTE["panel"], fg=PALETTE["text"], font=ui.FONT_TITLE)
        self.title.pack(anchor="w", pady=(12, 4))

        self.subtitle = tk.Label(
            card,
            text="",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
            wraplength=340,
            justify="left",
        )
        self.subtitle.pack(anchor="w", pady=(0, 18))

        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()

        pw_block = tk.Frame(card, bg=PALETTE["panel"])
        pw_block.pack(fill="x")
        self.pw_block = pw_block
        tk.Label(
            pw_block, text="主密码", bg=PALETTE["panel"], fg=PALETTE["text_soft"], font=ui.FONT_SMALL
        ).pack(anchor="w")
        self.password_entry = ui.entry(pw_block, self.password_var, show="\u25cf", width=30)
        self.password_entry.pack(fill="x", pady=(4, 0), ipady=4)
        self.password_entry.bind("<Return>", lambda _e: self._submit())

        # 仅"首次设置"时显示的两块内容
        self.confirm_frame = tk.Frame(card, bg=PALETTE["panel"])
        tk.Label(
            self.confirm_frame, text="再输一次", bg=PALETTE["panel"], fg=PALETTE["text_soft"], font=ui.FONT_SMALL
        ).pack(anchor="w")
        self.confirm_entry = ui.entry(self.confirm_frame, self.confirm_var, show="\u25cf", width=30)
        self.confirm_entry.pack(fill="x", pady=(4, 0), ipady=4)
        self.confirm_entry.bind("<Return>", lambda _e: self._submit())

        # 数据文件丢失但存在加密备份时显示的恢复提示条
        self.restore_banner = tk.Frame(card, bg=PALETTE["ok_soft"], padx=10, pady=8)

        self.strength_frame = tk.Frame(card, bg=PALETTE["panel"])
        self.strength_canvas = tk.Canvas(
            self.strength_frame, height=6, bg=PALETTE["border"], highlightthickness=0, bd=0
        )
        self.strength_canvas.pack(fill="x", pady=(8, 2))
        self.strength_bar = self.strength_canvas.create_rectangle(0, 0, 0, 6, fill=PALETTE["muted"], outline="")
        self.strength_text = tk.Label(
            self.strength_frame, text="强度：—", bg=PALETTE["panel"], fg=PALETTE["muted"], font=ui.FONT_SMALL
        )
        self.strength_text.pack(anchor="e")
        self.password_var.trace_add("write", lambda *_: self._update_strength())

        self.warning = tk.Label(
            card,
            text="主密码不会保存在任何地方，忘记后无法找回，建议写在纸上离线保存。",
            bg=PALETTE["danger_soft"],
            fg=PALETTE["danger"],
            font=ui.FONT_SMALL,
            wraplength=340,
            justify="left",
            padx=10,
            pady=7,
        )

        self.message = tk.Label(
            card,
            text="",
            bg=PALETTE["bg"],
            fg=PALETTE["danger"],
            font=ui.FONT_SMALL,
            wraplength=340,
            justify="left",
            padx=10,
            pady=6,
        )
        self.message.pack(fill="x", pady=(14, 0))
        self.message.pack_forget()

        self.submit = ui.Button(card, "解锁", self._submit, kind="primary", padx=14, pady=6)
        self.submit.pack(fill="x", pady=(18, 0))

        self.footer = tk.Label(
            card,
            text=f"数据保存在本机 · 版本 {__version__}",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
        )
        self.footer.pack(anchor="center", pady=(16, 0))

    # ---- 状态
    def show_setup(self) -> None:
        self.mode = "setup"
        self.title.configure(text="创建密码库")
        self.subtitle.configure(
            text="首次使用，请设置一个主密码。所有账号信息都会用它加密后保存在本机。"
        )
        self.confirm_frame.pack(fill="x", pady=(12, 0), before=self.submit)
        self.strength_frame.pack(fill="x", pady=(4, 0), before=self.submit)
        self.warning.pack(fill="x", pady=(12, 0), before=self.submit)
        self.submit.configure(text="创建密码库")
        self._set_message("")
        self.password_var.set("")
        self.confirm_var.set("")
        self.password_entry.focus_set()

    def show_unlock(self, message: str = "") -> None:
        self.mode = "unlock"
        self.confirm_frame.pack_forget()
        self.strength_frame.pack_forget()
        self.warning.pack_forget()
        self.title.configure(text="解锁密码库")
        self.subtitle.configure(text="输入主密码，解密本机保存的账号数据。")
        self.submit.configure(text="解锁")
        self._set_message(message)
        self.password_var.set("")
        self.submit.set_enabled(True)
        self.password_entry.focus_set()

    def show_restore_offer(self, backup_path: Path) -> None:
        """数据文件不见了但还留有历史备份：在创建界面顶部提示一键恢复。"""
        for child in self.restore_banner.winfo_children():
            child.destroy()
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(backup_path.stat().st_mtime))
        except OSError:
            stamp = "未知时间"

        row = tk.Frame(self.restore_banner, bg=PALETTE["ok_soft"])
        row.pack(fill="x")
        ui.Button(
            row,
            "从备份恢复",
            self.app.restore_latest_backup,
            kind="primary",
            padx=10,
            pady=3,
        ).pack(side="right", padx=(8, 0))
        text_box = tk.Frame(row, bg=PALETTE["ok_soft"])
        text_box.pack(side="left", fill="x", expand=True)
        tk.Label(
            text_box,
            text="检测到历史加密备份",
            bg=PALETTE["ok_soft"],
            fg=PALETTE["ok"],
            font=ui.FONT_SMALL_BOLD,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            text_box,
            text=f"最近一次：{stamp}。可用它恢复之前的账号数据（需要该备份的主密码）。",
            bg=PALETTE["ok_soft"],
            fg=PALETTE["text_soft"],
            font=ui.FONT_SMALL,
            wraplength=300,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        self.restore_banner.pack(fill="x", pady=(0, 12), before=self.pw_block)

    def hide_restore_offer(self) -> None:
        self.restore_banner.pack_forget()

    def focus(self) -> None:  # noqa: A003 - 与 Frame.focus 同名，这里故意覆盖
        self.password_entry.focus_set()

    # ---- 交互
    def _set_message(self, text: str, *, danger: bool = True) -> None:
        if text:
            self.message.configure(text=text, fg=PALETTE["danger"] if danger else PALETTE["text_soft"])
            self.message.pack(fill="x", pady=(14, 0), before=self.submit)
        else:
            self.message.pack_forget()

    def _update_strength(self) -> None:
        _score, label, color = util.password_strength(self.password_var.get())
        width = self.strength_canvas.winfo_width() or 330
        score = util.password_strength(self.password_var.get())[0]
        self.strength_canvas.coords(self.strength_bar, 0, 0, width * score / 5, 6)
        self.strength_canvas.itemconfigure(self.strength_bar, fill=color)
        self.strength_text.configure(text=f"强度：{label}")

    def _submit(self) -> None:
        password = self.password_var.get()
        if self.mode == "setup":
            confirm = self.confirm_var.get()
            if len(password) < 8:
                self._set_message("主密码至少需要 8 个字符。")
                return
            if password != confirm:
                self._set_message("两次输入的密码不一致。")
                return
            try:
                self.app.vault.initialize(password)
            except store.VaultError as exc:
                self._set_message(str(exc))
                return
            self.password_var.set("")
            self.confirm_var.set("")
            self._set_message("")
            self.app.enter_vault()
            return

        if not password:
            self._set_message("请输入主密码。")
            return
        self._set_busy(True)
        try:
            self.app.vault.unlock(password)
        except store.BadPassword as exc:
            self._set_message(str(exc))
            self._set_busy(False)
            self.password_var.set("")
            self.password_entry.focus_set()
            return
        except store.VaultError as exc:
            self._set_message(str(exc))
            self._set_busy(False)
            return
        self._set_busy(False)
        self.password_var.set("")
        self._set_message("")
        self.app.enter_vault()

    def _set_busy(self, busy: bool) -> None:
        self.submit.set_enabled(not busy)
        self.submit.configure(text="解锁中…" if busy else "解锁")


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class VaultView(tk.Frame):
    def __init__(self, app: "PasswordVaultApp") -> None:
        super().__init__(app, bg=PALETTE["bg"])
        self.app = app
        self.vault = app.vault

        self.accounts: list[dict] = []
        self.links: list[dict] = []
        self.groups: list[dict] = []
        self.filter_kind = "all"
        self.filter_value = ""
        self.query = ""
        self.selected_id: int | None = None
        self.selected_group_id: int | None = None
        self.expanded_groups: set[int] = set()
        self.revealed: set[int] = set()
        self._rows: dict[int, tuple[tk.Frame, list[tk.Widget], bool]] = {}
        self._toast_job = None

        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self) -> None:
        self._build_topbar()
        body = tk.Frame(self, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=PALETTE["panel"], width=190)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ui.vline(body).pack(side="left", fill="y")

        listpane = tk.Frame(body, bg=PALETTE["panel"], width=340)
        listpane.pack(side="left", fill="y")
        listpane.pack_propagate(False)
        ui.vline(body).pack(side="left", fill="y")

        detailpane = tk.Frame(body, bg=PALETTE["bg"])
        detailpane.pack(side="left", fill="both", expand=True)

        self.sidebar_scroll = ui.ScrollFrame(sidebar, bg=PALETTE["panel"])
        self.sidebar_scroll.pack(fill="both", expand=True, padx=8, pady=8)

        head = tk.Frame(listpane, bg=PALETTE["panel"])
        head.pack(fill="x", padx=14, pady=(12, 6))
        self.list_title = tk.Label(
            head, text="全部账号", bg=PALETTE["panel"], fg=PALETTE["text"], font=ui.FONT_H3
        )
        self.list_title.pack(side="left")
        self.list_count = ui.chip(head, "0")
        self.list_count.pack(side="right")

        self.list_scroll = ui.ScrollFrame(listpane, bg=PALETTE["panel"])
        self.list_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.list_empty = tk.Frame(listpane, bg=PALETTE["panel"])
        self.list_empty_label = tk.Label(
            self.list_empty,
            text="还没有账号",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_BODY,
            justify="center",
        )
        self.list_empty_label.pack(pady=(70, 0))

        self.detail_scroll = ui.ScrollFrame(detailpane, bg=PALETTE["bg"])
        self.detail_scroll.pack(fill="both", expand=True)

        self._toast = tk.Label(
            self, bg=PALETTE["text"], fg="#ffffff", font=ui.FONT_SMALL, padx=14, pady=6
        )

    def _build_topbar(self) -> None:
        bar = tk.Frame(self, bg=PALETTE["panel"], height=58)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        inner = tk.Frame(bar, bg=PALETTE["panel"])
        inner.pack(fill="both", expand=True, padx=14, pady=9)

        tk.Label(
            inner, text="密码库", bg=PALETTE["panel"], fg=PALETTE["text"], font=ui.FONT_H2
        ).pack(side="left")

        self._menu_btn = ui.Button(inner, "⋯", command=self._open_menu, kind="ghost", padx=10)
        self._menu_btn.pack(side="right")
        ui.Button(inner, "＋ 新建账号", command=self._new_account, kind="primary").pack(
            side="right", padx=(0, 8)
        )

        self.search = ui.PlaceholderEntry(inner, "搜索名称 / 用户名 / 邮箱 / 标签…")
        self.search.pack(side="left", fill="x", expand=True, padx=18, ipady=4)
        self.search.bind("<KeyRelease>", self._on_search)

        self._menu = tk.Menu(
            self,
            tearoff=0,
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            activebackground=PALETTE["accent_soft"],
            activeforeground=PALETTE["text"],
            bd=0,
            relief="flat",
            font=ui.FONT_BODY,
        )
        self._menu.add_command(label="修改主密码", command=self._change_master)
        self._menu.add_command(label="新建账号组…", command=self._new_group)
        self._menu.add_command(label="导出明文备份…", command=self._export)
        self._menu.add_command(label="备份加密副本…", command=self.app._backup_to_folder)
        self._menu.add_command(label="从备份恢复…", command=self.app._restore_backup)
        self._menu.add_separator()
        self._menu.add_command(label="立即锁定", command=self.app.lock)
        self._menu.add_command(label="关于", command=self._about)

        ui.hline(self).pack(fill="x", side="top")

    # ------------------------------------------------------------------ 数据
    def reset_view(self) -> None:
        """解锁后来到主界面时回到"全部账号 + 空搜索"的初始状态。"""
        self.query = ""
        self.search.clear()
        self.filter_kind = "all"
        self.filter_value = ""
        self.selected_id = None
        self.selected_group_id = None

    def reload(self, select_id: int | None = None) -> None:
        data = self.vault.snapshot()
        self.accounts = data["accounts"]
        self.links = data["links"]
        self.groups = data.get("groups", [])

        if select_id is not None:
            self.selected_id = select_id
            self.selected_group_id = None
        elif self.selected_id is not None and not any(a["id"] == self.selected_id for a in self.accounts):
            self.selected_id = None
        if self.selected_group_id is not None and not any(
            g["id"] == self.selected_group_id for g in self.groups
        ):
            self.selected_group_id = None

        if self.selected_id is None and self.selected_group_id is None:
            items = self._visible_items()
            if items:
                first = items[0]
                if first[0] == "group":
                    self.selected_group_id = first[1]["id"]
                else:
                    self.selected_id = first[1]["id"]

        self._render_sidebar()
        self._render_list()
        self._render_detail()

    def _account(self, account_id: int | None) -> dict | None:
        if account_id is None:
            return None
        return next((a for a in self.accounts if a["id"] == account_id), None)

    def _group(self, group_id: int | None) -> dict | None:
        if group_id is None:
            return None
        return next((g for g in self.groups if g["id"] == group_id), None)

    def _filtered(self) -> list[dict]:
        query = self.query.strip().lower()
        result = []
        for account in self.accounts:
            if self.filter_kind == "fav" and not account["favorite"]:
                continue
            if self.filter_kind == "kind" and account["kind"] != self.filter_value:
                continue
            if self.filter_kind == "category" and (account["category"] or "未分类") != self.filter_value:
                continue
            if self.filter_kind == "tag" and self.filter_value not in account["tags"]:
                continue
            if query:
                haystack = " ".join(
                    [
                        account["title"],
                        "邮箱账号" if account["kind"] == "email" else "账号",
                        account.get("username", ""),
                        account.get("email", ""),
                        account.get("url", ""),
                        account.get("category", ""),
                        account.get("notes", ""),
                        " ".join(account["tags"]),
                    ]
                ).lower()
                if query not in haystack:
                    continue
            result.append(account)
        result.sort(key=lambda a: (not a["favorite"], -a["updated"]))
        return result

    def _filter_title(self) -> str:
        if self.query.strip():
            return "搜索结果"
        if self.filter_kind == "fav":
            return "收藏"
        if self.filter_kind == "kind":
            return "账号" if self.filter_value == "account" else "邮箱账号"
        if self.filter_kind == "category":
            return self.filter_value
        if self.filter_kind == "tag":
            return f"# {self.filter_value}"
        return "全部账号"

    def _empty_text(self) -> str:
        if self.query.strip():
            return f"没有找到与「{self.query.strip()}」匹配的账号"
        if self.filter_kind == "fav":
            return "还没有收藏的账号\n在详情里点「☆ 收藏」即可加入"
        if self.filter_kind == "kind":
            return "还没有邮箱账号\n新建时把类型选为「邮箱账号」" if self.filter_value == "email" else "还没有普通账号"
        if self.filter_kind == "category":
            return "这个分类下还没有账号"
        if self.filter_kind == "tag":
            return "这个标签下还没有账号"
        return "还没有账号\n点右上角「＋ 新建账号」开始"

    # ------------------------------------------------------------------ 渲染：侧栏
    def _render_sidebar(self) -> None:
        inner = self.sidebar_scroll.inner
        for child in inner.winfo_children():
            child.destroy()

        total = len(self.accounts)
        fav = sum(1 for account in self.accounts if account["favorite"])
        self._side_section(inner, "全部")
        self._side_item(inner, "全部账号", total, self.filter_kind == "all", lambda: self.set_filter("all"))
        self._side_item(inner, "★ 收藏", fav, self.filter_kind == "fav", lambda: self.set_filter("fav"))

        type_counts = Counter(account["kind"] for account in self.accounts)
        self._side_section(inner, "类型")
        self._side_item(
            inner,
            "账号",
            type_counts.get("account", 0),
            self.filter_kind == "kind" and self.filter_value == "account",
            lambda: self.set_filter("kind", "account"),
        )
        self._side_item(
            inner,
            "邮箱账号",
            type_counts.get("email", 0),
            self.filter_kind == "kind" and self.filter_value == "email",
            lambda: self.set_filter("kind", "email"),
        )

        categories = Counter((account["category"] or "未分类") for account in self.accounts)
        self._side_section(inner, "分类")
        if not categories:
            self._side_empty(inner, "暂无分类")
        for name, count in sorted(categories.items(), key=lambda kv: (kv[0] == "未分类", kv[0])):
            self._side_item(
                inner,
                name,
                count,
                self.filter_kind == "category" and self.filter_value == name,
                lambda n=name: self.set_filter("category", n),
            )

        tags = Counter(tag for account in self.accounts for tag in account["tags"])
        self._side_section(inner, "标签")
        if not tags:
            self._side_empty(inner, "暂无标签")
        for name, count in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:24]:
            self._side_item(
                inner,
                f"# {name}",
                count,
                self.filter_kind == "tag" and self.filter_value == name,
                lambda n=name: self.set_filter("tag", n),
            )

    def _side_section(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL_BOLD,
        ).pack(anchor="w", padx=8, pady=(10, 3))

    def _side_empty(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent, text=text, bg=PALETTE["panel"], fg=PALETTE["muted"], font=ui.FONT_SMALL
        ).pack(anchor="w", padx=10, pady=(0, 4))

    def _side_item(self, parent: tk.Misc, text: str, count: int, active: bool, command) -> None:
        bg = PALETTE["accent_soft"] if active else PALETTE["panel"]
        row = tk.Frame(parent, bg=bg, padx=9, pady=5, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        label = tk.Label(
            row,
            text=text,
            bg=bg,
            fg=PALETTE["accent_dark"] if active else PALETTE["text_soft"],
            font=ui.FONT_BODY_BOLD if active else ui.FONT_BODY,
            anchor="w",
        )
        label.pack(side="left")
        number = tk.Label(row, text=str(count), bg=bg, fg=PALETTE["muted"], font=ui.FONT_SMALL)
        number.pack(side="right")

        hover = PALETTE["accent_soft"] if active else PALETTE["row_hover"]

        def on_enter(_event):
            for widget in (row, label, number):
                widget.configure(bg=hover)

        def on_leave(_event):
            for widget in (row, label, number):
                widget.configure(bg=bg)

        for widget in (row, label, number):
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

    def set_filter(self, kind: str, value: str = "") -> None:
        self.filter_kind = kind
        self.filter_value = value
        self._render_sidebar()
        self._render_list()

    # ------------------------------------------------------------------ 渲染：列表
    def _on_search(self, _event=None) -> None:
        self.query = self.search.value()
        self._render_list()

    def _visible_items(self) -> list[tuple]:
        """列表要显示的内容：``("group", group, members)`` 或 ``("account", account)``。

        无搜索、无筛选时，属于账号组的账号折叠进组行；一旦搜索或筛选，
        就退回平铺显示，方便直接找到某个成员账号。
        """
        rows = sorted(self._filtered(), key=lambda a: (not a["favorite"], -a["updated"]))
        flat_mode = bool(self.query.strip()) or self.filter_kind != "all"
        if flat_mode:
            return [("account", account) for account in rows]

        by_id = {account["id"]: account for account in rows}
        grouped_ids = {account_id for group in self.groups for account_id in group["member_ids"]}
        items: list[tuple] = []
        for group in sorted(self.groups, key=lambda g: (g["name"].lower(), g["id"])):
            members = [by_id[account_id] for account_id in group["member_ids"] if account_id in by_id]
            items.append(("group", group, members))
        for account in rows:
            if account["id"] in grouped_ids:
                continue
            items.append(("account", account))
        return items

    def _render_list(self) -> None:
        self.list_scroll.clear()
        self._rows.clear()
        items = self._visible_items()
        self.list_title.configure(text=self._filter_title())
        self.list_count.configure(text=str(len(items)))

        if not items:
            self.list_scroll.pack_forget()
            self.list_empty_label.configure(text=self._empty_text())
            self.list_empty.pack(fill="both", expand=True)
            return

        self.list_empty.pack_forget()
        self.list_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        for item in items:
            if item[0] == "group":
                group, members = item[1], item[2]
                self._build_group_row(group, members)
                if group["id"] in self.expanded_groups:
                    for account in members:
                        self._build_row(account, indent=26)
            else:
                self._build_row(item[1])

    def _build_group_row(self, group: dict, members: list[dict]) -> None:
        selected = self.selected_group_id == group["id"]
        expanded = group["id"] in self.expanded_groups
        bg = PALETTE["row_active"] if selected else PALETTE["panel"]

        row = tk.Frame(self.list_scroll.inner, bg=bg, padx=8, pady=6, cursor="hand2")
        row.pack(fill="x", padx=4, pady=(2, 0))

        arrow = tk.Label(
            row,
            text="▾" if expanded else "▸",
            bg=bg,
            fg=PALETTE["muted"],
            font=ui.FONT_BODY,
            cursor="hand2",
        )
        arrow.pack(side="left", padx=(0, 6))
        arrow.bind("<Button-1>", lambda _e: self._toggle_group(group["id"]))

        avatar = tk.Label(
            row,
            text="组",
            bg=PALETTE["group"],
            fg="#ffffff",
            font=ui.FONT_SMALL_BOLD,
            width=2,
            pady=5,
        )
        avatar.pack(side="left", padx=(0, 10))

        text_col = tk.Frame(row, bg=bg)
        text_col.pack(side="left", fill="x", expand=True)

        title_line = tk.Frame(text_col, bg=bg)
        title_line.pack(fill="x")
        title = tk.Label(
            title_line, text=group["name"], bg=bg, fg=PALETTE["text"], font=ui.FONT_BODY_BOLD, anchor="w"
        )
        title.pack(side="left")
        count_chip = tk.Label(
            title_line,
            text=f"{len(members)} 个账号",
            bg=PALETTE["group_soft"],
            fg=PALETTE["group"],
            font=ui.FONT_SMALL,
            padx=6,
        )
        count_chip.pack(side="left", padx=(6, 0))
        if any(member["favorite"] for member in members):
            tk.Label(title_line, text="★", bg=bg, fg=PALETTE["star"], font=ui.FONT_SMALL).pack(
                side="left", padx=(4, 0)
            )

        subtitle_text = " · ".join(member["title"] for member in members[:4]) or "暂无成员"
        if len(members) > 4:
            subtitle_text += f" 等 {len(members)} 个"
        subtitle = tk.Label(
            text_col, text=subtitle_text, bg=bg, fg=PALETTE["muted"], font=ui.FONT_SMALL, anchor="w"
        )
        subtitle.pack(fill="x")

        hover_bg = PALETTE["row_active"] if selected else PALETTE["row_hover"]

        def on_enter(_event):
            if group["id"] != self.selected_group_id:
                for widget in (row, text_col, title_line, title, subtitle):
                    widget.configure(bg=hover_bg)

        def on_leave(_event):
            if group["id"] != self.selected_group_id:
                for widget in (row, text_col, title_line, title, subtitle):
                    widget.configure(bg=bg)

        for widget in (row, text_col, title_line, title, subtitle):
            widget.bind("<Button-1>", lambda _e: self.select_group(group["id"]))
            widget.bind("<Double-Button-1>", lambda _e: self._edit_group(group))
            widget.bind("<Button-3>", lambda e: self._group_row_menu(e, group))
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

    def _toggle_group(self, group_id: int) -> None:
        if group_id in self.expanded_groups:
            self.expanded_groups.discard(group_id)
        else:
            self.expanded_groups.add(group_id)
        self._render_list()

    def select_group(self, group_id: int) -> None:
        self.selected_group_id = group_id
        self.selected_id = None
        self.expanded_groups.add(group_id)
        self._render_list()
        self._render_detail()
        self.detail_scroll.reset_scroll()

    def _group_row_menu(self, event, group: dict) -> None:
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            activebackground=PALETTE["accent_soft"],
            activeforeground=PALETTE["text"],
            bd=0,
            relief="flat",
            font=ui.FONT_BODY,
        )
        menu.add_command(label="编辑账号组", command=lambda: self._edit_group(group))
        menu.add_command(label="展开/收起", command=lambda: self._toggle_group(group["id"]))
        menu.add_separator()
        menu.add_command(label="删除账号组", command=lambda: self._delete_group(group))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _build_row(self, account: dict, *, indent: int = 0) -> None:
        selected = account["id"] == self.selected_id
        bg = PALETTE["row_active"] if selected else PALETTE["panel"]
        is_email = account["kind"] == "email"
        row = tk.Frame(self.list_scroll.inner, bg=bg, padx=9, pady=7, cursor="hand2")
        row.pack(fill="x", padx=(4 + indent, 4), pady=2)

        avatar = tk.Label(
            row,
            text=util.avatar_letter(account["title"]),
            bg=PALETTE["ok"] if is_email else PALETTE["accent"],
            fg="#ffffff",
            font=ui.FONT_AVATAR,
            width=2,
            pady=3,
        )
        avatar.pack(side="left", padx=(0, 10))

        text_col = tk.Frame(row, bg=bg)
        text_col.pack(side="left", fill="x", expand=True)

        title_line = tk.Frame(text_col, bg=bg)
        title_line.pack(fill="x")
        title = tk.Label(
            title_line, text=account["title"], bg=bg, fg=PALETTE["text"], font=ui.FONT_BODY_BOLD, anchor="w"
        )
        title.pack(side="left")
        widgets: list[tk.Widget] = [row, text_col, title_line, title]
        if account["favorite"]:
            star = tk.Label(title_line, text="★", bg=bg, fg=PALETTE["star"], font=ui.FONT_SMALL)
            star.pack(side="left", padx=(4, 0))
            widgets.append(star)
        badge: tk.Label | None = None
        if is_email:
            badge = tk.Label(
                title_line,
                text="邮箱",
                bg=PALETTE["ok_soft"],
                fg=PALETTE["ok"],
                font=ui.FONT_SMALL,
                padx=5,
            )
            badge.pack(side="left", padx=(6, 0))

        subtitle_text = account.get("email") or account.get("username") or account.get("url") or "未填写账号信息"
        subtitle = tk.Label(
            text_col, text=subtitle_text, bg=bg, fg=PALETTE["muted"], font=ui.FONT_SMALL, anchor="w"
        )
        subtitle.pack(fill="x")
        widgets.append(subtitle)

        hover_widgets = list(widgets)
        if badge is not None:
            widgets.append(badge)

        hover_bg = PALETTE["row_active"] if selected else PALETTE["row_hover"]

        def on_enter(_event, items=hover_widgets):
            if account["id"] != self.selected_id:
                for widget in items:
                    widget.configure(bg=hover_bg)

        def on_leave(_event, items=hover_widgets):
            if account["id"] != self.selected_id:
                for widget in items:
                    widget.configure(bg=bg)

        for widget in widgets:
            widget.bind("<Button-1>", lambda _e, aid=account["id"]: self.select(aid))
            widget.bind("<Double-Button-1>", lambda _e, aid=account["id"]: self._edit_account(aid))
            widget.bind("<Button-3>", lambda e, aid=account["id"]: self._row_menu(e, aid))
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        self._rows[account["id"]] = (row, widgets, selected)

    def select(self, account_id: int) -> None:
        self.selected_group_id = None
        self.selected_id = account_id
        self._render_list()
        self._render_detail()
        self.detail_scroll.reset_scroll()

    def _row_menu(self, event, account_id: int) -> None:
        account = self._account(account_id)
        if not account:
            return
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            activebackground=PALETTE["accent_soft"],
            activeforeground=PALETTE["text"],
            bd=0,
            relief="flat",
            font=ui.FONT_BODY,
        )
        menu.add_command(label="复制密码", command=lambda: self.copy(account["password"], "密码"))
        menu.add_command(label="复制用户名", command=lambda: self.copy(account["username"], "用户名"))
        menu.add_separator()
        menu.add_command(label="编辑账号", command=lambda: self._edit_account(account_id))
        menu.add_command(label="删除账号", command=lambda: self._delete_account(account_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------ 渲染：详情
    def _render_detail(self) -> None:
        inner = self.detail_scroll.inner
        for child in inner.winfo_children():
            child.destroy()

        wrap = tk.Frame(inner, bg=PALETTE["bg"])
        wrap.pack(fill="both", expand=True, padx=22, pady=18)

        group = self._group(self.selected_group_id)
        if group is not None:
            self._render_group_detail(wrap, group)
            return

        account = self._account(self.selected_id)
        if account is None:
            tk.Label(
                wrap,
                text="从左侧选择一个账号，查看密码与关联的账号",
                bg=PALETTE["bg"],
                fg=PALETTE["muted"],
                font=ui.FONT_BODY,
            ).pack(pady=(90, 0))
            return

        card = tk.Frame(
            wrap, bg=PALETTE["panel"], padx=22, pady=18, highlightthickness=1, highlightbackground=PALETTE["border"]
        )
        card.pack(fill="both", expand=True)

        links = [l for l in self.links if l["a_id"] == account["id"] or l["b_id"] == account["id"]]
        is_email = account["kind"] == "email"

        # ---- 头部
        header = tk.Frame(card, bg=PALETTE["panel"])
        header.pack(fill="x")
        tk.Label(
            header,
            text=util.avatar_letter(account["title"]),
            bg=PALETTE["ok"] if is_email else PALETTE["accent"],
            fg="#ffffff",
            font=ui.FONT_TITLE,
            width=2,
            pady=2,
        ).pack(side="left", padx=(0, 14))

        titles = tk.Frame(header, bg=PALETTE["panel"])
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text=account["title"],
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            font=ui.FONT_H2,
            anchor="w",
            justify="left",
            wraplength=self._wrap_width(),
        ).pack(anchor="w")

        meta = tk.Frame(titles, bg=PALETTE["panel"])
        meta.pack(anchor="w", pady=(5, 0))
        ui.chip(meta, "邮箱账号" if is_email else "账号", "ok" if is_email else "accent").pack(
            side="left", padx=(0, 6)
        )
        if account["category"]:
            ui.chip(meta, account["category"], "accent").pack(side="left", padx=(0, 6))
        if account["favorite"]:
            ui.chip(meta, "★ 已收藏", "star").pack(side="left", padx=(0, 6))
        ui.chip(meta, f"{len(links)} 个关联", "neutral").pack(side="left", padx=(0, 6))
        ui.chip(meta, f"更新于 {util.fmt_time(account['updated'])}", "neutral").pack(side="left")

        actions = tk.Frame(header, bg=PALETTE["panel"])
        actions.pack(side="right", padx=(10, 0))
        ui.Button(
            actions,
            "★ 取消收藏" if account["favorite"] else "☆ 收藏",
            lambda: self._toggle_favorite(account),
            kind="soft",
            padx=8,
        ).pack(side="left", padx=(0, 6))
        ui.Button(actions, "编辑", lambda: self._edit_account(account["id"]), kind="secondary", padx=10).pack(
            side="left", padx=(0, 6)
        )
        ui.Button(actions, "删除", lambda: self._delete_account(account["id"]), kind="danger", padx=10).pack(
            side="left"
        )

        ui.hline(card).pack(fill="x", pady=(14, 6))

        # ---- 字段
        fields = tk.Frame(card, bg=PALETTE["panel"])
        fields.pack(fill="x")
        self._detail_field(fields, "用户名", account["username"], "用户名")
        self._detail_field(fields, "邮箱地址" if is_email else "邮箱", account["email"], "邮箱")
        self._password_field(fields, account)
        self._detail_field(fields, "网址", account["url"], "网址")
        if not account["url"]:
            self._derived_login_row(fields, account)
        if account["notes"]:
            self._detail_field(fields, "备注", account["notes"], "备注", copy=False)

        if account["tags"]:
            tag_row = tk.Frame(card, bg=PALETTE["panel"])
            tag_row.pack(fill="x", pady=(6, 0))
            tk.Label(
                tag_row, text="标签", bg=PALETTE["panel"], fg=PALETTE["muted"], font=ui.FONT_SMALL, width=8, anchor="w"
            ).pack(side="left")
            tag_box = tk.Frame(tag_row, bg=PALETTE["panel"])
            tag_box.pack(side="left", fill="x", expand=True)
            for tag in account["tags"]:
                ui.chip(tag_box, f"# {tag}").pack(side="left", padx=(0, 6), pady=2)

        # ---- 关联账号
        self._render_links(card, account, links)

    def _render_group_detail(self, parent: tk.Misc, group: dict) -> None:
        members = [account for account in (self._account(aid) for aid in group["member_ids"]) if account]

        card = tk.Frame(
            parent,
            bg=PALETTE["panel"],
            padx=22,
            pady=18,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        card.pack(fill="both", expand=True)

        header = tk.Frame(card, bg=PALETTE["panel"])
        header.pack(fill="x")
        tk.Label(
            header,
            text="组",
            bg=PALETTE["group"],
            fg="#ffffff",
            font=ui.FONT_TITLE,
            width=2,
            pady=2,
        ).pack(side="left", padx=(0, 14))

        titles = tk.Frame(header, bg=PALETTE["panel"])
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text=group["name"],
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            font=ui.FONT_H2,
            anchor="w",
            justify="left",
            wraplength=self._wrap_width(),
        ).pack(anchor="w")

        meta = tk.Frame(titles, bg=PALETTE["panel"])
        meta.pack(anchor="w", pady=(5, 0))
        ui.chip(meta, "账号组", "accent").pack(side="left", padx=(0, 6))
        ui.chip(meta, f"{len(members)} 个账号", "neutral").pack(side="left", padx=(0, 6))
        ui.chip(meta, f"更新于 {util.fmt_time(group['updated'])}", "neutral").pack(side="left")

        actions = tk.Frame(header, bg=PALETTE["panel"])
        actions.pack(side="right", padx=(10, 0))
        ui.Button(actions, "编辑组", lambda: self._edit_group(group), kind="secondary", padx=10).pack(
            side="left", padx=(0, 6)
        )
        ui.Button(actions, "删除组", lambda: self._delete_group(group), kind="danger", padx=10).pack(
            side="left"
        )

        ui.hline(card).pack(fill="x", pady=(14, 6))

        tk.Label(
            card,
            text="组内账号",
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            font=ui.FONT_H3,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            card,
            text="每个账号的密码各自独立，可分别复制",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        if not members:
            tk.Label(
                card,
                text="这个组还没有成员。点「编辑组」勾选账号。",
                bg=PALETTE["soft"],
                fg=PALETTE["muted"],
                font=ui.FONT_SMALL,
                pady=10,
            ).pack(fill="x")
        for account in members:
            row = tk.Frame(card, bg=PALETTE["soft"], padx=10, pady=6)
            row.pack(fill="x", pady=(0, 6))
            tk.Label(
                row,
                text=util.avatar_letter(account["title"]),
                bg=PALETTE["ok"] if account["kind"] == "email" else PALETTE["accent"],
                fg="#ffffff",
                font=ui.FONT_SMALL_BOLD,
                width=2,
            ).pack(side="left", padx=(0, 8))

            name_col = tk.Frame(row, bg=PALETTE["soft"])
            name_col.pack(side="left", fill="x", expand=True)
            account_label = tk.Label(
                name_col,
                text=account["title"],
                bg=PALETTE["soft"],
                fg=PALETTE["text"],
                font=ui.FONT_BODY_BOLD,
                anchor="w",
                cursor="hand2",
            )
            account_label.pack(anchor="w")
            account_label.bind("<Button-1>", lambda _e, aid=account["id"]: self.select(aid))
            sub_text = account.get("username") or account.get("email") or "未填写账号信息"
            sub = tk.Label(
                name_col,
                text=sub_text,
                bg=PALETTE["soft"],
                fg=PALETTE["muted"],
                font=ui.FONT_SMALL,
                anchor="w",
                cursor="hand2",
            )
            sub.pack(anchor="w")
            sub.bind("<Button-1>", lambda _e, aid=account["id"]: self.select(aid))

            ui.Button(
                row,
                "复制密码",
                command=lambda a=account: self.copy(a.get("password", ""), f"「{a['title']}」的密码"),
                kind="ghost",
                padx=6,
            ).pack(side="right")
            ui.Button(
                row,
                "打开",
                command=lambda aid=account["id"]: self.select(aid),
                kind="ghost",
                padx=6,
            ).pack(side="right")

        if group["note"]:
            tk.Label(
                card,
                text="备注",
                bg=PALETTE["panel"],
                fg=PALETTE["muted"],
                font=ui.FONT_SMALL,
                anchor="w",
            ).pack(anchor="w", pady=(12, 2))
            tk.Label(
                card,
                text=group["note"],
                bg=PALETTE["soft"],
                fg=PALETTE["text_soft"],
                font=ui.FONT_BODY,
                justify="left",
                anchor="w",
                wraplength=self._wrap_width(),
                padx=10,
                pady=8,
            ).pack(fill="x")

    def _wrap_width(self) -> int:
        """详情区当前可用宽度（用于长文本换行）。"""
        width = self.detail_scroll.canvas.winfo_width() or 480
        return max(140, width - 190)

    def _detail_field(
        self,
        parent: tk.Misc,
        label: str,
        value: str,
        copy_label: str,
        *,
        copy: bool = True,
    ) -> None:
        row = tk.Frame(parent, bg=PALETTE["panel"])
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text=label,
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
            width=8,
            anchor="w",
        ).pack(side="left", anchor="n", pady=(2, 0))

        shown = value if value else "未填写"
        is_url = copy_label == "网址" and value.lower().startswith(("http://", "https://"))
        value_label = tk.Label(
            row,
            text=shown,
            bg=PALETTE["panel"],
            fg=(PALETTE["accent_dark"] if is_url else PALETTE["text"]) if value else PALETTE["muted"],
            font=ui.FONT_BODY,
            anchor="w",
            justify="left",
            wraplength=self._wrap_width() if value and len(value) > 60 else 0,
            cursor="hand2" if is_url else "",
        )
        value_label.pack(side="left", fill="x", expand=True, pady=(1, 0))
        if is_url:
            value_label.bind("<Button-1>", lambda _e: webbrowser.open(value))

        if value and copy:
            ui.Button(
                row, "复制", command=lambda: self.copy(value, copy_label), kind="ghost", padx=8
            ).pack(side="right")

    def _derived_login_row(self, parent: tk.Misc, account: dict) -> None:
        """网址为空时，按邮箱后缀给出对应服务商的登录页入口。"""
        provider = util.lookup_email_provider(account.get("email", ""))
        if not provider:
            return
        name, url = provider
        row = tk.Frame(parent, bg=PALETTE["panel"])
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text="登录页",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
            width=8,
            anchor="w",
        ).pack(side="left", anchor="n", pady=(2, 0))
        link = tk.Label(
            row,
            text=f"打开 {name} 登录页",
            bg=PALETTE["panel"],
            fg=PALETTE["accent_dark"],
            font=ui.FONT_BODY,
            cursor="hand2",
            anchor="w",
        )
        link.pack(side="left", fill="x", expand=True, pady=(1, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(url))

    def _password_field(self, parent: tk.Misc, account: dict) -> None:
        password = account["password"]
        row = tk.Frame(parent, bg=PALETTE["panel"])
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text="密码",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
            width=8,
            anchor="w",
        ).pack(side="left", anchor="n", pady=(2, 0))

        if password:
            revealed = account["id"] in self.revealed
            shown = password if revealed else "\u25cf" * min(len(password), 14)
            tk.Label(
                row,
                text=shown,
                bg=PALETTE["panel"],
                fg=PALETTE["text"],
                font=ui.FONT_MONO,
                anchor="w",
            ).pack(side="left", fill="x", expand=True, pady=(1, 0))

            ui.Button(
                row,
                "隐藏" if revealed else "显示",
                lambda: self._toggle_reveal(account["id"]),
                kind="ghost",
                padx=8,
            ).pack(side="right")
            ui.Button(
                row, "复制", command=lambda: self.copy(password, "密码"), kind="ghost", padx=8
            ).pack(side="right")
        else:
            tk.Label(
                row, text="未填写", bg=PALETTE["panel"], fg=PALETTE["muted"], font=ui.FONT_SMALL, anchor="w"
            ).pack(side="left")

    def _render_links(self, card: tk.Misc, account: dict, links: list[dict]) -> None:
        section = tk.Frame(card, bg=PALETTE["panel"])
        section.pack(fill="x", pady=(18, 0))

        head = tk.Frame(section, bg=PALETTE["panel"])
        head.pack(fill="x")
        tk.Label(
            head, text="关联账号", bg=PALETTE["panel"], fg=PALETTE["text"], font=ui.FONT_H3
        ).pack(side="left")
        tk.Label(
            head,
            text="密码各自独立，可分别复制",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=ui.FONT_SMALL,
        ).pack(side="left", padx=(8, 0))
        ui.Button(head, "＋ 添加关联", command=self._add_link, kind="soft", padx=9).pack(side="right")

        if not links:
            tk.Label(
                section,
                text="还没有关联账号。可以把它的绑定邮箱、主账号等关联起来。",
                bg=PALETTE["soft"],
                fg=PALETTE["muted"],
                font=ui.FONT_SMALL,
                pady=10,
            ).pack(fill="x", pady=(8, 0))
            return

        for link in links:
            outgoing = link["a_id"] == account["id"]
            other_id = link["b_id"] if outgoing else link["a_id"]
            other = self._account(other_id)
            target_title = other["title"] if other else "（已删除的账号）"
            target_sub = ""
            if other:
                target_sub = other.get("username") or other.get("email") or ""

            row = tk.Frame(section, bg=PALETTE["soft"], padx=10, pady=7)
            row.pack(fill="x", pady=(6, 0))
            tk.Label(
                row,
                text="→" if outgoing else "←",
                bg=PALETTE["soft"],
                fg=PALETTE["muted"],
                font=ui.FONT_BODY,
            ).pack(side="left", padx=(0, 6))
            ui.chip(row, link["relation"], "accent").pack(side="left", padx=(0, 8))
            target = tk.Label(
                row,
                text=target_title,
                bg=PALETTE["soft"],
                fg=PALETTE["accent_dark"],
                font=ui.FONT_BODY_BOLD,
                cursor="hand2",
            )
            target.pack(side="left")
            target.bind("<Button-1>", lambda _e, oid=other_id: self.select(oid) if self._account(oid) else None)
            if target_sub:
                tk.Label(
                    row, text=target_sub, bg=PALETTE["soft"], fg=PALETTE["muted"], font=ui.FONT_SMALL
                ).pack(side="left", padx=(6, 0))
            ui.Button(
                row,
                "复制密码",
                command=lambda o=other: self._copy_related(o),
                kind="ghost",
                padx=6,
            ).pack(side="right", padx=(0, 4))
            ui.Button(
                row,
                "移除",
                command=lambda lid=link["id"]: self._remove_link(lid),
                kind="ghost",
                padx=6,
            ).pack(side="right")

    def _copy_related(self, account: dict | None) -> None:
        """复制关联账号自己的密码（与当前账号的密码是两回事）。"""
        if not account:
            return
        self.copy(account.get("password", ""), f"「{account['title']}」的密码")

    # ------------------------------------------------------------------ 动作
    def _toggle_reveal(self, account_id: int) -> None:
        if account_id in self.revealed:
            self.revealed.discard(account_id)
        else:
            self.revealed.add(account_id)
        self._render_detail()

    def _toggle_favorite(self, account: dict) -> None:
        try:
            self.vault.update_account(account["id"], {"favorite": not account["favorite"]})
        except store.VaultError as exc:
            show_error(self, "操作失败", str(exc))
            return
        self.reload(select_id=account["id"])
        self._show_toast("已收藏" if not account["favorite"] else "已取消收藏")

    def _new_account(self) -> None:
        saved = AccountEditorDialog(self, self.vault, self.accounts, self.links).show()
        if saved:
            self.reload(select_id=saved["id"])
            self._show_toast("账号已添加")

    def _edit_account(self, account_id: int) -> None:
        account = self._account(account_id)
        if not account:
            return
        saved = AccountEditorDialog(self, self.vault, self.accounts, self.links, account).show()
        if saved:
            self.reload(select_id=saved["id"])
            self._show_toast("已保存修改")

    def _delete_account(self, account_id: int) -> None:
        account = self._account(account_id)
        if not account:
            return
        if not ask_yes_no(
            self,
            "删除账号",
            f"确定删除「{account['title']}」吗？\n它的密码和相关关联都会被删除，且无法恢复。",
            danger=True,
        ):
            return
        try:
            self.vault.delete_account(account_id)
        except store.VaultError as exc:
            show_error(self, "删除失败", str(exc))
            return
        if self.selected_id == account_id:
            self.selected_id = None
        self.reload()
        self._show_toast("已删除")

    def _add_link(self) -> None:
        account = self._account(self.selected_id)
        if not account:
            return
        others = [a for a in self.accounts if a["id"] != account["id"]]
        if not others:
            show_info(self, "暂无可关联账号", "至少需要两个账号才能建立关联，请先新建一个账号。")
            return
        link = LinkDialog(self, self.vault, account, self.accounts).show()
        if link:
            self.reload(select_id=account["id"])
            self._show_toast("已建立关联")

    def _remove_link(self, link_id: int) -> None:
        try:
            self.vault.delete_link(link_id)
        except store.VaultError as exc:
            show_error(self, "移除失败", str(exc))
            return
        self.reload(select_id=self.selected_id)
        self._show_toast("已移除关联")

    # ---- 账号组
    def _new_group(self) -> None:
        if not self.accounts:
            show_info(self, "还没有账号", "先添加账号，再把它们组合成一个账号组。")
            return
        saved = GroupDialog(self, self.vault, self.accounts).show()
        if not saved:
            return
        self.selected_group_id = saved["id"]
        self.selected_id = None
        self.expanded_groups.add(saved["id"])
        self.reload()
        self._show_toast("账号组已创建")

    def _edit_group(self, group: dict) -> None:
        saved = GroupDialog(self, self.vault, self.accounts, group).show()
        if not saved:
            return
        self.selected_group_id = saved["id"]
        self.reload()
        self._show_toast("账号组已保存")

    def _delete_group(self, group: dict) -> None:
        if not ask_yes_no(
            self,
            "删除账号组",
            f"确定删除账号组「{group['name']}」吗？\n组内的账号不会被删除，只是不再归在这个组里。",
        ):
            return
        try:
            self.vault.delete_group(group["id"])
        except store.VaultError as exc:
            show_error(self, "删除失败", str(exc))
            return
        if self.selected_group_id == group["id"]:
            self.selected_group_id = None
        self.expanded_groups.discard(group["id"])
        self.reload()
        self._show_toast("账号组已删除")

    def _open_menu(self) -> None:
        x = self._menu_btn.winfo_rootx()
        y = self._menu_btn.winfo_rooty() + self._menu_btn.winfo_height() + 2
        try:
            self._menu.tk_popup(x, y)
        finally:
            self._menu.grab_release()

    def _change_master(self) -> None:
        if ChangeMasterDialog(self, self.vault).show():
            self._show_toast("主密码已修改")

    def _about(self) -> None:
        AboutDialog(self, __version__, str(self.app.db_path)).show()

    def _export(self) -> None:
        if not ask_yes_no(
            self,
            "导出明文备份",
            "导出的 JSON 文件包含所有账号的明文密码，任何拿到文件的人都能直接看到。\n"
            "建议只用于一次性迁移，用完后立即删除。是否继续？",
            danger=True,
        ):
            return
        filename = f"密码库导出-{time.strftime('%Y%m%d-%H%M')}.json"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出明文备份",
            defaultextension=".json",
            initialfile=filename,
            filetypes=[("JSON 文件", "*.json")],
        )
        if not path:
            return
        try:
            data = self.vault.export_plain()
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, store.VaultError) as exc:
            show_error(self, "导出失败", str(exc))
            return
        show_info(self, "导出完成", f"已导出到：\n{path}")

    # ------------------------------------------------------------------ 剪贴板 / 提示
    def copy(self, text: str, label: str) -> None:
        if not text:
            self._show_toast("没有可复制的内容")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        self._show_toast(f"已复制{label}，30 秒后自动清除剪贴板")
        self.after(30000, lambda: self._clear_clipboard(text))

    def _clear_clipboard(self, expected: str) -> None:
        try:
            if self.clipboard_get() == expected:
                self.clipboard_clear()
                self.clipboard_append("")
        except tk.TclError:
            pass

    def _show_toast(self, message: str) -> None:
        self._toast.configure(text=message)
        self._toast.place(relx=0.5, rely=0.965, anchor="s")
        if self._toast_job is not None:
            try:
                self.after_cancel(self._toast_job)
            except tk.TclError:
                pass
        self._toast_job = self.after(3000, lambda: self._toast.place_forget())

    def focus_search(self) -> None:
        self.search.focus_set()
        self.search.select_range(0, "end")


# --------------------------------------------------------------------------- #
# 应用
# --------------------------------------------------------------------------- #
class PasswordVaultApp(tk.Tk):
    def __init__(
        self,
        db_path: Path,
        *,
        idle_minutes: float = 15.0,
        backup_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.withdraw()
        self.title("密码库 · 本地密码管理器")
        self.configure(bg=PALETTE["bg"])
        self.minsize(1000, 660)
        ui.init_style(self)
        self._set_icon()

        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir) if backup_dir else util.default_backup_dir(self.db_path)
        self.vault = store.Vault(self.db_path, idle_timeout=idle_minutes * 60)

        self.auth_view = AuthView(self)
        self.vault_view = VaultView(self)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<ButtonPress>", self._on_activity, add="+")
        self.bind_all("<KeyPress>", self._on_activity, add="+")
        self.bind_all("<Control-f>", self._focus_search, add="+")
        self.bind_all("<Control-F>", self._focus_search, add="+")

        if self.vault.initialized:
            self.auth_view.show_unlock()
        else:
            self.auth_view.show_setup()
            # 数据文件不存在/为空，但备份目录里还有历史库 → 提供一键恢复
            candidate = self._latest_backup()
            if candidate is not None:
                self.auth_view.show_restore_offer(candidate)
        self.auth_view.pack(fill="both", expand=True)

        ui.center_window(self, 1180, 760)
        self.deiconify()
        self.after(15000, self._check_idle)

    def _set_icon(self) -> None:
        try:
            image = tk.PhotoImage(width=32, height=32)
            image.put(PALETTE["accent"], to=(0, 0, 32, 32))
            image.put("#ffffff", to=(8, 14, 24, 26))
            image.put("#ffffff", to=(12, 6, 20, 14))
            image.put(PALETTE["accent"], to=(15, 18, 17, 22))
            self.iconphoto(True, image)
        except tk.TclError:
            pass

    # ---- 状态切换
    def enter_vault(self) -> None:
        self.auth_view.pack_forget()
        self.vault_view.pack(fill="both", expand=True)
        self.vault_view.reset_view()
        self.vault_view.reload()
        self._auto_backup()

    def lock(self, message: str = "") -> None:
        self.vault.lock()
        self.vault_view.pack_forget()
        self.auth_view.show_unlock(message)
        self.auth_view.pack(fill="both", expand=True)

    # ---- 加密备份 / 恢复
    def _auto_backup(self) -> None:
        """解锁后与退出前各备份一次（加密副本，项目目录之外，自动轮转）。"""
        if not self.vault.unlocked:
            return
        try:
            self.vault.backup(self.backup_dir)
        except (store.VaultError, OSError, sqlite3.Error):
            pass

    def _latest_backup(self) -> Path | None:
        try:
            files = [
                path
                for path in self.backup_dir.glob("vault-*.db")
                if path.is_file() and store.looks_like_vault(path)
            ]
        except OSError:
            return None
        if not files:
            return None
        try:
            files.sort(key=lambda path: path.stat().st_mtime)
        except OSError:
            return None
        return files[-1]

    def restore_latest_backup(self) -> None:
        """从自动备份里恢复（启动界面上的恢复按钮调用）。"""
        candidate = self._latest_backup()
        if candidate is None:
            show_error(self, "没有可用备份", "备份目录里还没有可恢复的密码库。")
            return
        if not ask_yes_no(
            self,
            "从备份恢复",
            f"将用这份备份替换当前密码库：\n{candidate}\n\n当前库里的内容会被覆盖。确定恢复吗？",
            danger=True,
        ):
            return
        if self._replace_with_backup(candidate):
            self.auth_view.hide_restore_offer()
            self.auth_view.show_unlock("已从备份恢复，请用该备份文件对应的主密码解锁。")

    def _backup_to_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="选择加密备份保存到哪个文件夹")
        if not folder:
            return
        try:
            target = self.vault.backup(folder)
        except (store.VaultError, OSError, sqlite3.Error) as exc:
            show_error(self, "备份失败", str(exc))
            return
        show_info(
            self,
            "加密备份完成",
            f"已保存：\n{target}\n\n文件本身用主密码加密，恢复时需要对应的主密码。",
        )

    def _restore_backup(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择加密备份文件（vault-*.db）",
            filetypes=[("密码库备份", "*.db"), ("所有文件", "*.*")],
        )
        if not path:
            return
        if not ask_yes_no(
            self,
            "从备份恢复",
            f"将用这份备份替换当前密码库：\n{path}\n\n当前库里的内容会被覆盖。确定恢复吗？",
            danger=True,
        ):
            return
        if self._replace_with_backup(path):
            self.auth_view.show_unlock("已从备份恢复，请用该备份文件对应的主密码解锁。")

    def _replace_with_backup(self, source: str | Path) -> bool:
        """关闭当前库 → 用备份覆盖 vault.db → 重新打开（之后需要解锁）。"""
        source_path = Path(source)
        try:
            if source_path.resolve() == self.db_path.resolve():
                return False
        except OSError:
            pass

        idle = self.vault.idle_timeout
        try:
            self.vault.close()
            for suffix in ("", "-wal", "-shm"):
                try:
                    Path(str(self.db_path) + suffix).unlink()
                except FileNotFoundError:
                    pass
            shutil.copy2(str(source_path), str(self.db_path))
            self.vault = store.Vault(self.db_path, idle_timeout=idle)
            self.vault_view.vault = self.vault
            self.vault_view.accounts = []
            self.vault_view.links = []
        except (OSError, store.VaultError) as exc:
            # 尽量恢复可用状态：重新打开（可能已经是空库或原库）
            try:
                self.vault = store.Vault(self.db_path, idle_timeout=idle)
                self.vault_view.vault = self.vault
            except Exception:  # noqa: BLE001 - 再失败就只能提示重启
                pass
            show_error(
                self,
                "恢复失败",
                f"{exc}\n\n如果提示文件被占用，请先关闭其他密码库窗口后重试。",
            )
            return False

        self.lock("")
        return True

    # ---- 事件
    def _focus_search(self, _event=None) -> None:
        if self.vault_view.winfo_ismapped():
            self.vault_view.focus_search()

    def _on_activity(self, _event=None) -> None:
        self.vault.touch()

    def _on_mousewheel(self, event):
        widget = event.widget
        while widget is not None:
            if isinstance(widget, ui.ScrollFrame):
                widget.scroll(event.delta)
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _check_idle(self) -> None:
        try:
            if self.vault.unlocked and self.vault.idle_expired():
                self.lock("密码库已闲置自动锁定，请重新输入主密码。")
        finally:
            try:
                self.after(15000, self._check_idle)
            except tk.TclError:
                pass

    def _on_close(self) -> None:
        self._auto_backup()
        try:
            self.vault.close()
        finally:
            self.destroy()
