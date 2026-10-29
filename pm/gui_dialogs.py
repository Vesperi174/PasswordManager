"""桌面客户端的各个弹窗：账号编辑、关联、密码生成、修改主密码、关于。"""

from __future__ import annotations

import shutil
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import store
from . import ui_kit as ui
from . import update
from . import util

PALETTE = ui.PALETTE

RELATION_PRESETS = (
    "绑定邮箱",
    "恢复邮箱",
    "主账号",
    "子账号",
    "两步验证",
    "支付方式",
    "同人账号",
    "关联",
)


def _label(parent: tk.Misc, text: str, *, font=None, fg=None, bg=None, **kwargs) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        font=font or ui.FONT_BODY,
        fg=fg or PALETTE["text"],
        bg=bg or ui.widget_bg(parent),
        **kwargs,
    )


def show_error(parent: tk.Misc, title: str, message: str) -> None:
    messagebox.showerror(title, message, parent=parent.winfo_toplevel())


def show_info(parent: tk.Misc, title: str, message: str) -> None:
    messagebox.showinfo(title, message, parent=parent.winfo_toplevel())


def ask_yes_no(parent: tk.Misc, title: str, message: str, *, danger: bool = False) -> bool:
    icon = messagebox.WARNING if danger else messagebox.QUESTION
    return messagebox.askyesno(title, message, parent=parent.winfo_toplevel(), icon=icon)


class Dialog(tk.Toplevel):
    """模态弹窗基类：内容区 + 右下角按钮区。"""

    def __init__(self, master: tk.Misc, title: str, *, width: int = 560) -> None:
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.configure(bg=PALETTE["bg"])
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self._width = width
        self.result = None

        self.body = tk.Frame(self, bg=PALETTE["bg"])
        self.body.pack(fill="both", expand=True, padx=22, pady=(18, 10))
        self.footer = tk.Frame(self, bg=PALETTE["bg"])
        self.footer.pack(fill="x", padx=22, pady=(0, 16))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())

    # ---- 通用构件
    def headline(self, title: str, subtitle: str | None = None) -> None:
        _label(self.body, title, font=ui.FONT_H2).pack(anchor="w")
        if subtitle:
            _label(
                self.body,
                subtitle,
                font=ui.FONT_SMALL,
                fg=PALETTE["muted"],
                justify="left",
                wraplength=self._width - 60,
            ).pack(anchor="w", pady=(3, 10))
        else:
            tk.Frame(self.body, bg=PALETTE["bg"], height=8).pack(fill="x")

    def field(self, parent: tk.Misc, text: str, widget: tk.Widget) -> tk.Frame:
        row = tk.Frame(parent, bg=PALETTE["bg"])
        _label(row, text, font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        widget.pack(fill="x", pady=(3, 0))
        return row

    def add_buttons(self, primary_text: str, primary_command) -> None:
        ui.Button(self.footer, "取消", self._cancel).pack(side="right", padx=(8, 0))
        ui.Button(self.footer, primary_text, primary_command, kind="primary").pack(side="right")

    def error_label(self) -> tk.Label:
        if not hasattr(self, "_error"):
            self._error = tk.Label(
                self.body,
                text="",
                bg=PALETTE["bg"],
                fg=PALETTE["danger"],
                font=ui.FONT_SMALL,
                wraplength=self._width - 60,
                justify="left",
            )
            self._error.pack(anchor="w", pady=(6, 0))
        return self._error

    def _set_error(self, message: str) -> None:
        label = self.error_label()
        label.configure(text=message)
        if message:
            label.pack(anchor="w", pady=(6, 0))
        else:
            label.pack_forget()

    # ---- 生命周期
    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self):
        self.update_idletasks()
        width = self._width
        height = max(self.winfo_reqheight(), 120)
        ui.center_window(self, width, height, self.master)
        self.deiconify()
        self.grab_set()
        self.lift()
        try:
            self.wait_window(self)
        except tk.TclError:
            pass
        return self.result


class PasswordGeneratorDialog(Dialog):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, "生成密码", width=430)
        self.headline("生成一个强密码", "用操作系统级随机源（secrets）生成，不会上传到任何地方。")
        self.length = tk.IntVar(value=20)
        self.use_lower = tk.BooleanVar(value=True)
        self.use_upper = tk.BooleanVar(value=True)
        self.use_digits = tk.BooleanVar(value=True)
        self.use_symbols = tk.BooleanVar(value=True)

        length_row = tk.Frame(self.body, bg=PALETTE["bg"])
        length_row.pack(fill="x")
        _label(length_row, "长度", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(side="left")
        self.length_text = _label(length_row, "20", font=ui.FONT_SMALL_BOLD, fg=PALETTE["accent_dark"])
        self.length_text.pack(side="right")
        self.scale = tk.Scale(
            self.body,
            from_=8,
            to=64,
            orient="horizontal",
            variable=self.length,
            showvalue=0,
            command=self._on_length,
            bg=PALETTE["bg"],
            troughcolor=PALETTE["border"],
            activebackground=PALETTE["accent"],
            highlightthickness=0,
            bd=0,
            sliderlength=18,
        )
        self.scale.pack(fill="x", pady=(2, 8))

        opts = tk.Frame(self.body, bg=PALETTE["bg"])
        opts.pack(fill="x")
        for text, var in (
            ("大写 A-Z", self.use_upper),
            ("小写 a-z", self.use_lower),
            ("数字 0-9", self.use_digits),
            ("符号 !@#", self.use_symbols),
        ):
            ui.checkbutton(opts, text, var, command=self._regenerate).pack(side="left", padx=(0, 12))

        self.preview_var = tk.StringVar()
        preview = tk.Entry(
            self.body,
            textvariable=self.preview_var,
            font=ui.FONT_MONO,
            relief="flat",
            bd=0,
            bg=PALETTE["soft"],
            fg=PALETTE["text"],
            readonlybackground=PALETTE["soft"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        preview.pack(fill="x", pady=(12, 0), ipady=6)
        preview.configure(state="readonly")

        actions = tk.Frame(self.body, bg=PALETTE["bg"])
        actions.pack(fill="x", pady=(10, 0))
        ui.Button(actions, "重新生成", self._regenerate, kind="soft").pack(side="left")
        ui.Button(actions, "使用这段密码", self._use, kind="primary").pack(side="left", padx=(8, 0))
        ui.Button(self.footer, "取消", self._cancel).pack(side="right")

        self._regenerate()

    def _on_length(self, _value) -> None:
        self.length_text.configure(text=str(self.length.get()))
        self._regenerate()

    def _regenerate(self) -> None:
        self.preview_var.set(
            util.generate_password(
                self.length.get(),
                lower=self.use_lower.get(),
                upper=self.use_upper.get(),
                digits=self.use_digits.get(),
                symbols=self.use_symbols.get(),
            )
        )

    def _use(self) -> None:
        self.result = self.preview_var.get()
        self.destroy()


class AccountEditorDialog(Dialog):
    """新建 / 编辑账号。"""

    def __init__(self, master: tk.Misc, vault: store.Vault, accounts: list[dict], links: list[dict], account: dict | None = None) -> None:
        editing = account is not None
        super().__init__(master, "编辑账号" if editing else "新建账号", width=620)
        self.vault = vault
        self.accounts = accounts
        self.links = links
        self.account = account
        self.kind = (account or {}).get("kind") or store.DEFAULT_KIND
        self._kind_buttons: dict[str, tk.Button] = {}
        self._suggest_vars: dict[int, tk.BooleanVar] = {}
        self._link_direction = "out"
        self._create_email_var: tk.BooleanVar | None = None
        self._create_email_address = ""
        self._auto_url = ""

        self.headline(
            "编辑账号" if editing else "新建账号",
            "先选类型：账号是登录用的用户名 + 密码；邮箱账号是邮箱本身。"
            "填邮箱时可以把两者互相关联。",
        )

        self.title_var = tk.StringVar(value=(account or {}).get("title", ""))
        self.username_var = tk.StringVar(value=(account or {}).get("username", ""))
        self.email_var = tk.StringVar(value=(account or {}).get("email", ""))
        self.password_var = tk.StringVar(value=(account or {}).get("password", ""))
        self.url_var = tk.StringVar(value=(account or {}).get("url", ""))
        self.category_var = tk.StringVar(value=(account or {}).get("category", ""))
        self.tags_var = tk.StringVar(value=", ".join((account or {}).get("tags", [])))
        self.favorite_var = tk.BooleanVar(value=bool((account or {}).get("favorite")))

        # ---- 类型切换：账号 / 邮箱账号
        kind_box = tk.Frame(self.body, bg=PALETTE["bg"])
        kind_box.pack(fill="x", pady=(0, 10))
        _label(kind_box, "类型", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        seg = tk.Frame(kind_box, bg=PALETTE["bg"])
        seg.pack(anchor="w", pady=(4, 0))
        for value, text in (("account", "账号"), ("email", "邮箱账号")):
            button = tk.Button(
                seg,
                text=text,
                bd=0,
                relief="flat",
                cursor="hand2",
                padx=14,
                pady=4,
                command=lambda v=value: self._apply_kind(v),
            )
            button.pack(side="left", padx=(0, 8))
            self._kind_buttons[value] = button

        grid = tk.Frame(self.body, bg=PALETTE["bg"])
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="c")
        grid.columnconfigure(1, weight=1, uniform="c")

        def cell(row_index, column, text, factory, *, span=1, padx=(0, 0), pady=(0, 8)):
            """在网格中放一行：标签 + 控件（控件须以该行为父容器创建）。"""
            row = tk.Frame(grid, bg=PALETTE["bg"])
            label = _label(row, text, font=ui.FONT_SMALL, fg=PALETTE["text_soft"])
            label.pack(anchor="w")
            widget = factory(row)
            widget.pack(fill="x", pady=(3, 0))
            row.grid(row=row_index, column=column, columnspan=span, sticky="we", padx=padx, pady=pady)
            return row, widget, label

        self.title_row, self.title_entry, self._title_label = cell(
            0, 0, "名称 *", lambda p: ui.entry(p, self.title_var), span=2
        )
        self.username_row, self.username_entry, self._username_label = cell(
            1, 0, "用户名 / 登录账号", lambda p: ui.entry(p, self.username_var), padx=(0, 8)
        )
        self.email_row, self.email_entry, self._email_label = cell(
            1, 1, "绑定邮箱", lambda p: ui.entry(p, self.email_var)
        )

        # 「账号就是邮箱地址」：勾选后用户名自动跟随绑定邮箱
        self._account_is_email_var = tk.BooleanVar(value=False)
        self._account_is_email_cb = ui.checkbutton(
            self.username_row,
            "账号就是邮箱地址（只同步账号名）",
            self._account_is_email_var,
            command=self._sync_username_from_email,
        )
        self._account_is_email_cb.pack(anchor="w", pady=(4, 0))
        _label(
            self.username_row,
            "密码不参与同步：邮箱账号的密码在它自己的记录里，与这里的密码分开保存。",
            font=ui.FONT_SMALL,
            fg=PALETTE["muted"],
            wraplength=260,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))
        if account:
            username = (account.get("username") or "").strip().lower()
            email = (account.get("email") or "").strip().lower()
            if username and username == email:
                self._account_is_email_var.set(True)

        password_row = tk.Frame(grid, bg=PALETTE["bg"])
        _label(password_row, "密码", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        pw_line = tk.Frame(password_row, bg=PALETTE["bg"])
        pw_line.pack(fill="x", pady=(3, 0))
        self.password_entry = ui.entry(pw_line, self.password_var, show="\u25cf", font=ui.FONT_MONO)
        self.password_entry.pack(side="left", fill="x", expand=True)
        self._pw_visible = False
        self.show_password_btn = ui.Button(pw_line, "显示", self._toggle_password, kind="soft", padx=8)
        self.show_password_btn.pack(side="left", padx=(6, 0))
        ui.Button(pw_line, "生成", self._open_generator, kind="soft", padx=8).pack(side="left", padx=(6, 0))
        password_row.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 8))

        self.url_row, self.url_entry, _ = cell(3, 0, "网址", lambda p: ui.entry(p, self.url_var), span=2)
        self._url_hint = _label(
            self.url_row,
            "",
            font=ui.FONT_SMALL,
            fg=PALETTE["muted"],
            bg=PALETTE["bg"],
            anchor="w",
        )
        self._url_hint.pack(anchor="w", pady=(4, 0))

        _, self.category_entry, _ = cell(
            4,
            0,
            "分类",
            lambda p: ttk.Combobox(
                p,
                textvariable=self.category_var,
                style="Pm.TCombobox",
                font=ui.FONT_BODY,
                values=sorted({a["category"] for a in accounts if a["category"]}),
                state="normal",
            ),
            padx=(0, 8),
        )
        _, self.tags_entry, _ = cell(4, 1, "标签（逗号分隔）", lambda p: ui.entry(p, self.tags_var))

        notes_row = tk.Frame(self.body, bg=PALETTE["bg"])
        _label(notes_row, "备注", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        self.notes_text = ui.text_area(notes_row, height=3)
        self.notes_text.pack(fill="x", pady=(3, 0))
        self.notes_text.insert("1.0", (account or {}).get("notes", ""))
        notes_row.pack(fill="x", pady=(0, 6))

        ui.checkbutton(self.body, "标记为收藏", self.favorite_var).pack(anchor="w")

        self.suggest_frame = tk.Frame(self.body, bg=PALETTE["panel"], highlightthickness=1, highlightbackground=PALETTE["border"])
        self.email_var.trace_add("write", lambda *_: self._on_email_changed())
        self._apply_kind(self.kind)
        self._autofill_login_url()

        self.add_buttons("保存" if editing else "添加账号", self._save)

    # ---- 密码显示 / 生成
    def _toggle_password(self) -> None:
        self._pw_visible = not self._pw_visible
        self.password_entry.configure(show="" if self._pw_visible else "\u25cf")
        self.show_password_btn.configure(text="隐藏" if self._pw_visible else "显示")

    def _open_generator(self) -> None:
        value = PasswordGeneratorDialog(self).show()
        try:
            self.grab_set()  # 子弹窗关闭后恢复本弹窗的模态
        except tk.TclError:
            pass
        if value:
            self.password_var.set(value)
            if not self._pw_visible:
                self._toggle_password()

    # ---- 根据邮箱后缀自动识别登录网址
    def _on_email_changed(self) -> None:
        if self._account_is_email_var.get():
            self._sync_username_from_email()
        self._refresh_suggestions()
        self._autofill_login_url()

    def _sync_username_from_email(self) -> None:
        """勾选「账号就是邮箱地址」时，把绑定邮箱同步到用户名。"""
        if not self._account_is_email_var.get():
            return
        email = self.email_var.get().strip()
        if email:
            self.username_var.set(email)

    def _set_url_hint(self, text: str, replace_url: str | None = None) -> None:
        hint = self._url_hint
        hint.configure(text=text)
        hint.unbind("<Button-1>")
        if replace_url:
            hint.configure(fg=PALETTE["accent_dark"], cursor="hand2")
            hint.bind("<Button-1>", lambda _e: self._use_auto_url(replace_url))
        else:
            hint.configure(fg=PALETTE["muted"], cursor="")

    def _use_auto_url(self, url: str) -> None:
        self.url_var.set(url)
        self._auto_url = url
        self._set_url_hint(f"已填入登录网址：{url}")

    def _autofill_login_url(self) -> None:
        """邮箱后缀能识别出服务商时，自动填写其登录页地址。

        规则：
        * 网址为空、或仍是上次自动填入的地址 → 直接填写/更新；
        * 用户自己填过别的网址 → 只给出提示，点击提示文字才替换；
        * 换成无法识别的邮箱时，把上次自动填入的地址清掉，避免留下错误网址。
        """
        email = self.email_var.get().strip()
        current = self.url_var.get().strip()
        provider = util.lookup_email_provider(email)

        if provider is None:
            if self._auto_url and util.normalize_url(current) == util.normalize_url(self._auto_url):
                self.url_var.set("")
                self._auto_url = ""
                current = ""
            if current:
                self._set_url_hint("")
            elif email and "@" in email:
                self._set_url_hint("未识别到该邮箱的后缀，请手动填写网址")
            else:
                self._set_url_hint("")
            return

        name, url = provider
        if not current:
            self.url_var.set(url)
            self._auto_url = url
            self._set_url_hint(f"已根据邮箱后缀自动填写 {name} 登录页")
        elif util.normalize_url(current) == util.normalize_url(url):
            self._auto_url = url
            self._set_url_hint(f"已识别为 {name} 登录页")
        elif util.normalize_url(current) == util.normalize_url(self._auto_url):
            self.url_var.set(url)
            self._auto_url = url
            self._set_url_hint(f"已根据邮箱后缀自动填写 {name} 登录页")
        else:
            self._set_url_hint(f"识别到 {name} 登录页：{url}（点此替换）", replace_url=url)

    # ---- 类型切换（账号 / 邮箱账号）
    def _apply_kind(self, kind: str) -> None:
        self.kind = kind if kind in store.KINDS else store.DEFAULT_KIND
        email_mode = self.kind == "email"
        for value, button in self._kind_buttons.items():
            selected = value == self.kind
            button.configure(
                bg=PALETTE["accent_soft"] if selected else PALETTE["soft"],
                fg=PALETTE["accent_dark"] if selected else PALETTE["text_soft"],
                activebackground=PALETTE["accent_soft"] if selected else PALETTE["row_hover"],
                activeforeground=PALETTE["accent_dark"] if selected else PALETTE["text"],
                font=ui.FONT_BODY_BOLD if selected else ui.FONT_BODY,
            )
        if email_mode:
            self.username_row.grid_remove()
            self.email_row.grid(row=1, column=0, columnspan=2, sticky="we", padx=0, pady=(0, 8))
            self._email_label.configure(text="邮箱地址 *")
            self._title_label.configure(text="邮箱名称 *")
        else:
            self.username_row.grid(row=1, column=0, columnspan=1, sticky="we", padx=(0, 8), pady=(0, 8))
            self.email_row.grid(row=1, column=1, columnspan=1, sticky="we", padx=0, pady=(0, 8))
            self._email_label.configure(text="绑定邮箱")
            self._title_label.configure(text="名称 *")
        self._refresh_suggestions()

    # ---- 邮箱关联建议
    def _linked_ids(self) -> set[int]:
        if not self.account:
            return set()
        linked = set()
        for link in self.links:
            if link["a_id"] == self.account["id"]:
                linked.add(link["b_id"])
            elif link["b_id"] == self.account["id"]:
                linked.add(link["a_id"])
        return linked

    def _existing_email_account(self, email: str) -> list[dict]:
        """已有同地址的邮箱账号。"""
        return [
            account
            for account in self.accounts
            if account["kind"] == "email" and (account.get("email") or "").strip().lower() == email
        ]

    def _accounts_using_email(self, email: str) -> list[dict]:
        """把该邮箱当作登录名/登录邮箱来用的普通账号。"""
        return [
            account
            for account in self.accounts
            if account["kind"] != "email"
            and email
            in {
                (account.get("email") or "").strip().lower(),
                (account.get("username") or "").strip().lower(),
            }
        ]

    def _refresh_suggestions(self) -> None:
        for child in self.suggest_frame.winfo_children():
            child.destroy()
        self._suggest_vars.clear()
        self._create_email_var = None
        self._create_email_address = ""
        self._link_direction = "out"
        self.suggest_frame.pack_forget()

        email = self.email_var.get().strip().lower()
        if not util.looks_like_email(email):
            return

        editing_id = (self.account or {}).get("id")
        linked = self._linked_ids()

        if self.kind == "email":
            # 邮箱账号：把正在使用这个邮箱的普通账号关联进来（它们 → 本邮箱）
            targets = [
                account
                for account in self._accounts_using_email(email)
                if account["id"] != editing_id and account["id"] not in linked
            ][:4]
            if not targets:
                return
            headline = "以下账号使用这个邮箱，保存后互相关联（它们绑定到本邮箱）："
            self._link_direction = "into"
        else:
            targets = [
                account
                for account in self._existing_email_account(email)
                if account["id"] != editing_id and account["id"] not in linked
            ][:4]
            if targets:
                headline = "检测到同地址的邮箱账号，保存后建立「绑定邮箱」关联："
            else:
                targets = [
                    account
                    for account in self.accounts
                    if account["id"] != editing_id
                    and account["id"] not in linked
                    and email
                    in {
                        (account.get("email") or "").strip().lower(),
                        (account.get("username") or "").strip().lower(),
                        (account.get("title") or "").strip().lower(),
                    }
                ][:3]
                if targets:
                    headline = "检测到已有账号使用这个邮箱，保存后建立「绑定邮箱」关联："
                else:
                    # 还没有对应的邮箱账号：提供"顺带创建并互相绑定"的选项
                    self._create_email_address = email
                    self._create_email_var = tk.BooleanVar(value=True)
                    self.suggest_frame.pack(fill="x", pady=(10, 0))
                    _label(
                        self.suggest_frame,
                        "这个邮箱还没有对应的邮箱账号，可以一并创建并互相关联：",
                        font=ui.FONT_SMALL,
                        fg=PALETTE["accent_dark"],
                        bg=PALETTE["panel"],
                    ).pack(anchor="w", padx=10, pady=(8, 4))
                    ui.checkbutton(
                        self.suggest_frame,
                        f"创建邮箱账号「{email}」并建立「绑定邮箱」关联",
                        self._create_email_var,
                    ).pack(anchor="w", padx=10, pady=(0, 8))
                    return

        self.suggest_frame.pack(fill="x", pady=(10, 0))
        _label(
            self.suggest_frame,
            headline,
            font=ui.FONT_SMALL,
            fg=PALETTE["accent_dark"],
            bg=PALETTE["panel"],
        ).pack(anchor="w", padx=10, pady=(8, 2))
        for account in targets:
            var = tk.BooleanVar(value=True)
            self._suggest_vars[account["id"]] = var
            extra = account.get("username") or account.get("email") or ""
            name = account["title"] + (f"（{extra}）" if extra else "")
            ui.checkbutton(self.suggest_frame, name, var).pack(anchor="w", padx=10, pady=(0, 6))

    # ---- 保存
    def _save(self) -> None:
        self._set_error("")
        email = self.email_var.get().strip()
        title = self.title_var.get().strip()
        if self.kind == "email":
            if not email:
                self._set_error("邮箱账号请填写邮箱地址。")
                return
            if not title:
                title = email
                self.title_var.set(title)

        data = {
            "title": title,
            "kind": self.kind,
            "username": self.username_var.get().strip(),
            "email": email,
            "password": self.password_var.get(),
            "url": self.url_var.get().strip(),
            "category": self.category_var.get().strip(),
            "tags": [t.strip() for t in self.tags_var.get().replace("，", ",").split(",") if t.strip()],
            "notes": self.notes_text.get("1.0", "end").strip(),
            "favorite": self.favorite_var.get(),
        }
        if self.kind == "email" and not data["username"]:
            data["username"] = email
        if not data["title"]:
            self._set_error("请填写名称。")
            return
        if not any(data[key] for key in ("username", "email", "password", "url", "notes")):
            self._set_error("至少填写用户名、邮箱或密码中的一项。")
            return

        try:
            if self.account:
                saved = self.vault.update_account(self.account["id"], data)
            else:
                saved = self.vault.create_account(data)
        except store.VaultError as exc:
            self._set_error(str(exc))
            return

        # 账号 ↔ 邮箱账号 互相关联
        for target_id, var in self._suggest_vars.items():
            if not var.get():
                continue
            try:
                if self._link_direction == "into":
                    # 邮箱账号视角：普通账号 → 本邮箱
                    self.vault.create_link(target_id, saved["id"], "绑定邮箱")
                else:
                    # 普通账号视角：本账号 → 邮箱账号
                    self.vault.create_link(saved["id"], target_id, "绑定邮箱")
            except store.VaultError:
                pass

        if (
            self.kind != "email"
            and self._create_email_var is not None
            and self._create_email_var.get()
            and self._create_email_address
        ):
            try:
                email_account = self.vault.create_account(
                    {
                        "title": self._create_email_address,
                        "kind": "email",
                        "username": self._create_email_address,
                        "email": self._create_email_address,
                        "category": "邮箱",
                    }
                )
                self.vault.create_link(saved["id"], email_account["id"], "绑定邮箱")
            except store.VaultError:
                pass

        self.result = saved
        self.destroy()


class LinkDialog(Dialog):
    """给某个账号添加关联关系。"""

    def __init__(self, master: tk.Misc, vault: store.Vault, account: dict, accounts: list[dict]) -> None:
        super().__init__(master, "添加关联", width=520)
        self.vault = vault
        self.account = account
        self.accounts = [a for a in accounts if a["id"] != account["id"]]
        self._visible: list[dict] = []

        self.headline(
            "添加账号关联",
            f"含义：「{account['title']}」的某个关联类型指向另一个账号，"
            "例如它的绑定邮箱是哪个账号。",
        )

        self.relation_var = tk.StringVar(value="绑定邮箱")
        relation_box = tk.Frame(self.body, bg=PALETTE["bg"])
        _label(relation_box, "关联类型", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        combo_row = tk.Frame(relation_box, bg=PALETTE["bg"])
        combo_row.pack(fill="x", pady=(3, 0))
        relation_combo = ttk.Combobox(
            combo_row,
            textvariable=self.relation_var,
            values=list(RELATION_PRESETS),
            style="Pm.TCombobox",
            font=ui.FONT_BODY,
        )
        relation_combo.pack(side="left", fill="x", expand=True)
        chips = tk.Frame(relation_box, bg=PALETTE["bg"])
        chips.pack(fill="x", pady=(6, 0))
        for preset in RELATION_PRESETS[:4]:
            chip = tk.Label(
                chips,
                text=preset,
                bg=PALETTE["soft"],
                fg=PALETTE["text_soft"],
                font=ui.FONT_SMALL,
                padx=9,
                pady=2,
                cursor="hand2",
            )
            chip.pack(side="left", padx=(0, 6))
            chip.bind("<Button-1>", lambda _e, p=preset: self.relation_var.set(p))
        relation_box.pack(fill="x", pady=(0, 10))

        search_box = tk.Frame(self.body, bg=PALETTE["bg"])
        _label(search_box, "选择要关联的账号", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        self.search_entry = ui.entry(search_box)
        self.search_entry.pack(fill="x", pady=(3, 6))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._refresh_list())
        search_box.pack(fill="x", pady=(0, 6))

        list_wrap = tk.Frame(self.body, bg=PALETTE["border"], highlightthickness=1, highlightbackground=PALETTE["border"])
        list_wrap.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            list_wrap,
            height=8,
            font=ui.FONT_BODY,
            bd=0,
            relief="flat",
            highlightthickness=0,
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            selectbackground=PALETTE["accent_soft"],
            selectforeground=PALETTE["text"],
            activestyle="none",
            exportselection=False,
        )
        scrollbar = tk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview, width=11)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.listbox.bind("<Double-Button-1>", lambda _e: self._save())

        self.empty_hint = _label(self.body, "还没有其他账号，先新建一个账号再来关联。", font=ui.FONT_SMALL, fg=PALETTE["muted"])

        self.add_buttons("建立关联", self._save)
        self._refresh_list()

    def _refresh_list(self) -> None:
        query = self.search_entry.get().strip().lower()
        self._visible = [
            account
            for account in self.accounts
            if not query
            or query
            in " ".join(
                [account["title"], account.get("username", ""), account.get("email", ""), account.get("category", "")]
            ).lower()
        ]
        self.listbox.delete(0, "end")
        for account in self._visible:
            extra = account.get("username") or account.get("email") or account.get("category") or "未填写账号信息"
            self.listbox.insert("end", f"{account['title']}    ·    {extra}")
        if self._visible:
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self.empty_hint.pack_forget()
        else:
            self.empty_hint.pack(fill="x", pady=(6, 0))

    def _save(self) -> None:
        selection = self.listbox.curselection()
        if not selection or not self._visible:
            self._set_error("请先选择一个要关联的账号。")
            return
        target = self._visible[selection[0]]
        relation = self.relation_var.get().strip() or "关联"
        try:
            link = self.vault.create_link(self.account["id"], target["id"], relation)
        except store.VaultError as exc:
            self._set_error(str(exc))
            return
        self.result = link
        self.destroy()


class ChangeMasterDialog(Dialog):
    def __init__(self, master: tk.Misc, vault: store.Vault) -> None:
        super().__init__(master, "修改主密码", width=440)
        self.vault = vault
        self.headline("修改主密码", "会用新主密码重新加密全部账号，请牢记新密码。")

        self.old_var = tk.StringVar()
        self.new_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        for text, var in (
            ("当前主密码", self.old_var),
            ("新主密码（至少 8 位）", self.new_var),
            ("再输一次新主密码", self.confirm_var),
        ):
            row = tk.Frame(self.body, bg=PALETTE["bg"])
            _label(row, text, font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
            widget = ui.entry(row, var, show="\u25cf")
            widget.pack(fill="x", pady=(3, 0))
            row.pack(fill="x", pady=(0, 8))

        self.add_buttons("确认修改", self._save)

    def _save(self) -> None:
        self._set_error("")
        old = self.old_var.get()
        new = self.new_var.get()
        if len(new) < 8:
            self._set_error("新主密码至少需要 8 个字符。")
            return
        if new != self.confirm_var.get():
            self._set_error("两次输入的新密码不一致。")
            return
        try:
            self.vault.change_password(old, new)
        except store.BadPassword as exc:
            self._set_error(str(exc))
            return
        except store.VaultError as exc:
            self._set_error(str(exc))
            return
        self.result = True
        self.destroy()


class GroupDialog(Dialog):
    """新建 / 编辑账号组：命名 + 备注 + 勾选成员账号。"""

    def __init__(
        self,
        master: tk.Misc,
        vault: store.Vault,
        accounts: list[dict],
        group: dict | None = None,
    ) -> None:
        editing = group is not None
        super().__init__(master, "编辑账号组" if editing else "新建账号组", width=560)
        self.vault = vault
        self.accounts = list(accounts)
        self.group = group
        self.name_var = tk.StringVar(value=(group or {}).get("name", ""))
        self.note_var = tk.StringVar(value=(group or {}).get("note", ""))

        self.headline(
            "编辑账号组" if editing else "新建账号组",
            "把同一套东西打包成一个组（例如 Apex 游戏 + EA + Steam + 绑定邮箱），"
            "列表里只占一行，点开能看到每个账号自己的密码。",
        )

        name_row = tk.Frame(self.body, bg=PALETTE["bg"])
        _label(name_row, "组名 *", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        ui.entry(name_row, self.name_var, width=40).pack(fill="x", pady=(3, 0))
        name_row.pack(fill="x", pady=(0, 10))

        note_row = tk.Frame(self.body, bg=PALETTE["bg"])
        _label(note_row, "备注", font=ui.FONT_SMALL, fg=PALETTE["text_soft"]).pack(anchor="w")
        ui.entry(note_row, self.note_var, width=40).pack(fill="x", pady=(3, 0))
        note_row.pack(fill="x", pady=(0, 10))

        _label(
            self.body,
            "组内账号（勾选后保存）",
            font=ui.FONT_SMALL,
            fg=PALETTE["text_soft"],
        ).pack(anchor="w")

        holder = tk.Frame(
            self.body,
            bg=PALETTE["panel"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        holder.pack(fill="both", expand=True, pady=(4, 0))
        holder.configure(height=210)
        holder.pack_propagate(False)
        scroll = ui.ScrollFrame(holder, bg=PALETTE["panel"])
        scroll.pack(fill="both", expand=True)

        self.member_vars: dict[int, tk.BooleanVar] = {}
        existing = set((group or {}).get("member_ids", []))
        if not self.accounts:
            tk.Label(
                scroll.inner,
                text="还没有账号，先去添加账号再来建组。",
                bg=PALETTE["panel"],
                fg=PALETTE["muted"],
                font=ui.FONT_SMALL,
            ).pack(anchor="w", padx=10, pady=10)
        for account in self.accounts:
            row = tk.Frame(scroll.inner, bg=PALETTE["panel"])
            row.pack(fill="x", padx=8, pady=1)
            var = tk.BooleanVar(value=account["id"] in existing)
            self.member_vars[account["id"]] = var
            extra = account.get("username") or account.get("email") or ""
            label = account["title"] + (f"（{extra}）" if extra else "")
            if account.get("kind") == "email":
                label += "  [邮箱账号]"
            ui.checkbutton(row, label, var).pack(anchor="w")

        self.add_buttons("保存" if editing else "创建账号组", self._save)

    def _save(self) -> None:
        self._set_error("")
        name = self.name_var.get().strip()
        if not name:
            self._set_error("请填写账号组名称。")
            return
        member_ids = [account_id for account_id, var in self.member_vars.items() if var.get()]
        try:
            if self.group:
                saved = self.vault.update_group(
                    self.group["id"],
                    name=name,
                    note=self.note_var.get(),
                    member_ids=member_ids,
                )
            else:
                saved = self.vault.create_group(name, self.note_var.get(), member_ids)
        except store.VaultError as exc:
            self._set_error(str(exc))
            return
        self.result = saved
        self.destroy()


class UpdateDialog(Dialog):
    """检测更新：检查 GitHub 上的最新版本，可在线下载并替换程序文件。"""

    def __init__(self, master: tk.Misc, current_version: str, app, *, auto_check: bool = True) -> None:
        super().__init__(master, "检测更新", width=540)
        self.current_version = current_version
        self.app = app
        self._manifest: dict | None = None
        self._busy = False
        self._state = "checking"

        self.headline(
            "检测更新",
            f"当前版本 {current_version}。检查最新版本后可直接下载并更新，不需要打开浏览器或 GitHub。",
        )

        self.status = _label(
            self.body,
            "",
            font=ui.FONT_BODY,
            fg=PALETTE["text_soft"],
            wraplength=470,
            justify="left",
        )
        self.status.pack(anchor="w", pady=(6, 4))

        self.progress = ttk.Progressbar(self.body, mode="determinate", maximum=100)
        self.progress.configure(value=0)

        self.notes = tk.Text(
            self.body,
            height=6,
            wrap="word",
            font=ui.FONT_SMALL,
            relief="flat",
            bd=0,
            bg=PALETTE["soft"],
            fg=PALETTE["text_soft"],
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        self.notes.pack(fill="both", expand=True)
        self.notes.configure(state="disabled")

        self.close_btn = ui.Button(self.footer, "关闭", self._cancel)
        self.close_btn.pack(side="right", padx=(8, 0))
        self.restart_btn = ui.Button(self.footer, "立即重启", self._restart, kind="primary")
        self.action_btn = ui.Button(self.footer, "下载并更新", self._start_update, kind="primary")
        self.retry_btn = ui.Button(self.footer, "重试", self.start_check, kind="secondary")

        self._update_buttons()
        if auto_check:
            self.after(150, self.start_check)

    # ---- 状态
    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status.configure(text=text, fg=PALETTE["danger"] if error else PALETTE["text_soft"])

    def _set_notes(self, notes: list[str]) -> None:
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        for note in notes:
            self.notes.insert("end", f"· {note}\n")
        self.notes.configure(state="disabled")

    def _update_buttons(self) -> None:
        for button in (self.retry_btn, self.action_btn, self.restart_btn):
            if button.winfo_manager():
                button.pack_forget()
        if self._busy:
            return
        if self._state == "available":
            self.action_btn.pack(side="right", padx=(8, 0))
        elif self._state == "error":
            self.retry_btn.pack(side="right", padx=(8, 0))
        elif self._state == "done":
            self.restart_btn.pack(side="right", padx=(8, 0))

    def _after_safe(self, callback) -> None:
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    # ---- 检测
    def start_check(self) -> None:
        if self._busy:
            return
        self._state = "checking"
        self._busy = True
        self.progress.configure(value=0)
        self.progress.pack_forget()
        self._set_status("正在检测最新版本…")
        self._set_notes([])
        self._update_buttons()
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        try:
            manifest = update.fetch_manifest()
        except Exception as exc:  # noqa: BLE001 - 网络/格式问题都提示给用户
            self._after_safe(lambda: self._on_error(f"检测失败：{exc}"))
            return
        self._after_safe(lambda: self._on_manifest(manifest))

    def _on_manifest(self, manifest: dict) -> None:
        self._busy = False
        self._manifest = manifest
        version = str(manifest.get("version") or "")
        raw_notes = manifest.get("notes") or []
        notes = raw_notes if isinstance(raw_notes, list) else [str(raw_notes)]

        if update.is_newer(version, self.current_version):
            self._state = "available"
            self._set_status(
                f"发现新版本 {version}（当前 {self.current_version}）。"
                "下载后会先备份当前程序文件再替换，账号数据（data/）不受影响。"
            )
            self._set_notes([str(note) for note in notes])
        else:
            self._state = "latest"
            self._set_status(f"已是最新版本（{self.current_version}）。")
            self._set_notes([])
        self._update_buttons()

    def _on_error(self, message: str) -> None:
        self._busy = False
        self._state = "error"
        self._set_status(message, error=True)
        self._update_buttons()

    # ---- 下载与更新
    def _start_update(self) -> None:
        if self._busy or not self._manifest:
            return
        self._state = "downloading"
        self._busy = True
        self.progress.configure(value=0)
        self.progress.pack(fill="x", pady=(2, 6))
        self._set_status("正在下载更新包…")
        self._update_buttons()
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _set_progress(self, fraction: float) -> None:
        self.progress.configure(value=max(0, min(100, fraction * 100)))

    def _download_worker(self) -> None:
        manifest = self._manifest or {}
        try:
            work = Path(tempfile.mkdtemp(prefix="pm-update-"))
            zip_path = work / "update.zip"
            update.download_zip(
                str(manifest["download_url"]),
                zip_path,
                progress=lambda fraction: self._after_safe(lambda: self._set_progress(fraction)),
            )
            self._after_safe(lambda: self._set_status("正在安装更新（已备份当前程序文件）…"))
            backup = update.apply_update(zip_path)
            shutil.rmtree(work, ignore_errors=True)
            self._after_safe(lambda: self._on_done(backup))
        except Exception as exc:  # noqa: BLE001
            self._after_safe(lambda: self._on_error(f"更新失败：{exc}"))

    def _on_done(self, backup: Path) -> None:
        self._busy = False
        self._state = "done"
        self.progress.configure(value=100)
        self._set_status(f"更新完成，重启程序后生效。\n当前程序文件已备份到：{backup}")
        self._update_buttons()

    def _restart(self) -> None:
        self.app.prepare_relaunch()
        self.result = "restart"
        self.destroy()


class AboutDialog(Dialog):
    def __init__(self, master: tk.Misc, version: str, db_path: str) -> None:
        super().__init__(master, "关于", width=460)
        self.headline("关于密码库", f"版本 {version} · 纯 Python 标准库实现，无需安装第三方依赖。")
        info = (
            "· 数据文件：\n"
            f"  {db_path}\n\n"
            "· 加密方式：PBKDF2-HMAC-SHA256 派生密钥（60 万次迭代），\n"
            "  ChaCha20-Poly1305 认证加密（RFC 8439）。\n"
            "  标题、用户名、密码、备注全部加密后写入 SQLite。\n\n"
            "· 忘记主密码无法恢复，建议把主密码写在纸上离线保存。"
        )
        _label(
            self.body,
            info,
            font=ui.FONT_SMALL,
            fg=PALETTE["text_soft"],
            justify="left",
            wraplength=self._width - 60,
        ).pack(anchor="w")
        ui.Button(self.footer, "关闭", self._cancel, kind="primary").pack(side="right")
