"""界面自检：真实创建 Tk 窗口，驱动关键交互并检查渲染结果。

用法::

    python tools/gui_test.py

不需要人工点击：直接调用窗口内部方法模拟"设置主密码 → 建账号 → 加关联 →
搜索 → 收藏 → 锁定 → 解锁"，并检查界面上的文字是否符合预期。
"""

from __future__ import annotations

import shutil
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm import store  # noqa: E402
from pm import util  # noqa: E402
from pm.gui_app import PasswordVaultApp  # noqa: E402
from pm.gui_dialogs import (  # noqa: E402
    AboutDialog,
    AccountEditorDialog,
    ChangeMasterDialog,
    LinkDialog,
    PasswordGeneratorDialog,
)

PASSWORD = "CorrectHorse-Battery-2024"
NEW_PASSWORD = "NewMaster-Passphrase-99!"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [ok] {name}")
    else:
        failures.append(name)
        print(f"  [FAIL] {name} {detail}")


def collect_texts(widget: tk.Misc) -> list[str]:
    out: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(str(child.cget("text")))
        out.extend(collect_texts(child))
    return out


def collect_buttons(widget: tk.Misc) -> list[str]:
    out: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Button):
            text = str(child.cget("text")).strip()
            if text:
                out.append(text)
        out.extend(collect_buttons(child))
    return out


def main() -> int:
    workspace = Path(__file__).resolve().parent.parent
    tmp = workspace / ".tmp" / "gui"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    db_path = tmp / "vault.db"

    app = PasswordVaultApp(db_path, idle_minutes=999, backup_dir=tmp / "backups")
    app.update()
    tk_errors: list[str] = []
    app.report_callback_exception = lambda *args: tk_errors.append(repr(args))  # type: ignore[assignment]

    try:
        print("== 启动与首次设置 ==")
        check("首次启动显示设置模式", app.auth_view.mode == "setup")
        check("窗口尺寸合理", app.winfo_width() > 900 and app.winfo_height() > 600,
              f"{app.winfo_width()}x{app.winfo_height()}")

        # 输入两次不一致 → 应有错误提示
        app.auth_view.password_var.set("short")
        app.auth_view.confirm_var.set("different")
        app.auth_view._submit()
        app.update()
        check("过短主密码被拦下", app.auth_view.mode == "setup")
        check("错误提示可见", "至少" in app.auth_view.message.cget("text"))

        app.auth_view.password_var.set(PASSWORD)
        app.auth_view.confirm_var.set(PASSWORD)
        app.auth_view._submit()
        app.update()
        check("创建密码库后进入主界面", app.vault_view.winfo_ismapped() and not app.auth_view.winfo_ismapped())

        view = app.vault_view
        check("空库显示空状态文字", "还没有账号" in str(view.list_empty_label.cget("text")))

        print("== 列表 / 详情渲染 ==")
        vault = app.vault
        gmail = vault.create_account(
            {
                "title": "Gmail 主邮箱",
                "username": "octocat@gmail.com",
                "email": "octocat@gmail.com",
                "password": "MailPass!2024",
                "category": "邮箱",
                "tags": ["常用"],
            }
        )
        github = vault.create_account(
            {
                "title": "GitHub",
                "username": "octocat",
                "email": "octocat@gmail.com",
                "password": "Gh!p@ss-2024-xyz",
                "url": "https://github.com/login",
                "category": "开发",
                "tags": ["工作", "常用"],
                "notes": "已开启两步验证",
            }
        )
        view.reload(select_id=github["id"])
        app.update()

        check("列表渲染出 2 行", len(view._rows) == 2, str(len(view._rows)))
        check("列表计数正确", str(view.list_count.cget("text")) == "2", str(view.list_count.cget("text")))
        detail_texts = collect_texts(view.detail_scroll.inner)
        check("详情显示账号名", "GitHub" in detail_texts, str(detail_texts[:12]))
        check("详情显示用户名", "octocat" in detail_texts)
        check("详情显示分类", "开发" in detail_texts)
        check("详情显示关联提示", any("还没有关联账号" in t for t in detail_texts))
        check("密码默认打码", any("\u25cf" in t for t in detail_texts))

        # 显示密码
        view._toggle_reveal(github["id"])
        app.update()
        detail_texts = collect_texts(view.detail_scroll.inner)
        check("点击显示后看到明文密码", "Gh!p@ss-2024-xyz" in detail_texts)
        view._toggle_reveal(github["id"])
        app.update()

        print("== 搜索与筛选 ==")
        view.search.delete(0, "end")
        view.search.insert(0, "github")
        view._on_search()
        app.update()
        check("搜索过滤后只剩 1 行", len(view._rows) == 1, str(len(view._rows)))
        check("列表标题变为搜索结果", str(view.list_title.cget("text")) == "搜索结果")

        view.search.delete(0, "end")
        view.search.insert(0, "gmail")
        view._on_search()
        app.update()
        check("搜索命中邮箱时保留多条", len(view._rows) == 2, str(len(view._rows)))

        view.search.delete(0, "end")
        view._on_search()
        app.update()
        check("清空搜索恢复 2 行", len(view._rows) == 2)

        view.set_filter("category", "开发")
        app.update()
        check("分类筛选生效", len(view._rows) == 1)
        check("侧栏筛选标题正确", str(view.list_title.cget("text")) == "开发")
        view.set_filter("all")
        app.update()

        print("== 收藏 ==")
        view._toggle_favorite(github)
        app.update()
        check("收藏后数据已更新", next(a for a in view.accounts if a["id"] == github["id"])["favorite"] is True)
        check("收藏提示出现", "已收藏" in str(view._toast.cget("text")))
        view.set_filter("fav")
        app.update()
        check("收藏筛选只剩 1 行", len(view._rows) == 1)
        view.set_filter("all")
        app.update()

        print("== 关联展示 ==")
        vault.create_link(github["id"], gmail["id"], "绑定邮箱")
        view.reload(select_id=github["id"])
        app.update()
        detail_texts = collect_texts(view.detail_scroll.inner)
        check("详情显示关联类型", "绑定邮箱" in detail_texts, str(detail_texts))
        check("详情显示关联目标", "Gmail 主邮箱" in detail_texts)
        check("关联方向箭头存在", "→" in detail_texts)

        link = next(iter(vault.snapshot()["links"]))
        view._remove_link(link["id"])
        app.update()
        check("移除关联后详情更新", "绑定邮箱" not in collect_texts(view.detail_scroll.inner))
        vault.create_link(github["id"], gmail["id"], "绑定邮箱")
        view.reload(select_id=github["id"])
        app.update()

        print("== 剪贴板 ==")
        view.copy(github["password"], "密码")
        app.update()
        try:
            clip = app.clipboard_get()
        except tk.TclError:
            clip = ""
        check("复制密码到剪贴板", clip == "Gh!p@ss-2024-xyz", repr(clip))
        check("复制提示包含自动清除", "自动清除" in str(view._toast.cget("text")))
        view._clear_clipboard("Gh!p@ss-2024-xyz")
        app.update()

        print("== 新建账号弹窗 ==")
        editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        app.update()
        check("编辑弹窗可构建", editor.title_var.get() == "" and editor.winfo_exists())
        editor.title_var.set("Steam")
        editor.username_var.set("gamer")
        editor.email_var.set("octocat@gmail.com")
        editor.password_var.set("Steam-Pass-1")
        editor.tags_var.set("娱乐, 游戏")
        editor._save()
        app.update()
        check("弹窗保存后写入数据库", any(a["title"] == "Steam" for a in vault.snapshot()["accounts"]))
        check("邮箱匹配时自动建立绑定邮箱关联", any(
            l["relation"] == "绑定邮箱" and l["b_id"] == gmail["id"] for l in vault.snapshot()["links"]
        ))

        view.reload()
        app.update()
        check("新账号出现在列表", any(a.get("title") == "Steam" for a in view.accounts))

        print("== 关联弹窗 ==")
        link_dialog = LinkDialog(app, vault, github, view.accounts)
        app.update()
        link_dialog.search_entry.insert(0, "steam")
        link_dialog._refresh_list()
        check("关联弹窗搜索到 Steam", len(link_dialog._visible) == 1, str([a["title"] for a in link_dialog._visible]))
        link_dialog.relation_var.set("子账号")
        link_dialog.listbox.selection_set(0)
        link_dialog._save()
        app.update()
        links_after = vault.snapshot()["links"]
        check(
            "关联弹窗建立成功",
            any(l["relation"] == "子账号" for l in links_after),
            str([(l["relation"], l["a_id"], l["b_id"]) for l in links_after]),
        )

        print("== 密码生成器 ==")
        gen = PasswordGeneratorDialog(app)
        app.update()
        first = gen.preview_var.get()
        check("生成器默认 20 位", len(first) == 20, str(len(first)))
        gen.use_upper.set(False)
        gen.use_lower.set(False)
        gen.use_digits.set(False)
        gen.use_symbols.set(False)
        gen._regenerate()
        check("全不勾选也能生成", len(gen.preview_var.get()) == 20)
        gen.use_upper.set(True)
        gen.use_lower.set(True)
        gen.use_digits.set(True)
        gen._regenerate()
        second = gen.preview_var.get()
        check("两次生成结果不同", first != second)
        gen._use()
        check("使用按钮返回密码", isinstance(gen.result, str) and len(gen.result) == 20)

        check("util.generate_password 长度可控", len(util.generate_password(32)) == 32)
        check("util.generate_password 含四类字符", any(c.isupper() for c in util.generate_password(40))
              and any(c.islower() for c in util.generate_password(40))
              and any(c.isdigit() for c in util.generate_password(40))
              and any(not c.isalnum() for c in util.generate_password(40)))

        print("== 修改主密码 ==")
        change = ChangeMasterDialog(app, vault)
        app.update()
        change.old_var.set("wrong")
        change.new_var.set(NEW_PASSWORD)
        change.confirm_var.set(NEW_PASSWORD)
        change._save()
        check("原密码错误时不关闭弹窗", change.winfo_exists())
        check("原密码错误提示", "错误" in str(change._error.cget("text")), str(change._error.cget("text")))
        change.old_var.set(PASSWORD)
        change._save()
        app.update()
        check("修改主密码成功", change.result is True)

        print("== 锁定 / 解锁 ==")
        app.lock("已自动锁定（测试）")
        app.update()
        check("锁定后回到解锁界面", app.auth_view.mode == "unlock" and app.auth_view.winfo_ismapped())
        check("锁定提示可见", "自动锁定" in str(app.auth_view.message.cget("text")))

        app.auth_view.password_var.set(PASSWORD)
        app.auth_view._submit()
        app.update()
        check("旧主密码无法解锁", app.auth_view.mode == "unlock")
        check("错误提示已显示", "主密码错误" in str(app.auth_view.message.cget("text")))

        app.auth_view.password_var.set(NEW_PASSWORD)
        app.auth_view._submit()
        app.update()
        check("新主密码解锁成功", app.vault_view.winfo_ismapped())
        check("解锁后数据仍在", len(app.vault_view.accounts) == 3, str(len(app.vault_view.accounts)))

        print("== 空闲自动锁定 ==")
        app.vault.idle_timeout = -1
        app._check_idle()
        app.update()
        check("空闲超时自动锁定", app.auth_view.mode == "unlock" and not app.vault.unlocked)
        app.vault.idle_timeout = 999 * 60
        app.auth_view.password_var.set(NEW_PASSWORD)
        app.auth_view._submit()
        app.update()
        check("重新解锁恢复", app.vault_view.winfo_ismapped())

        print("== 关于弹窗 ==")
        about = AboutDialog(app, "1.0.0", str(db_path))
        app.update()
        texts = collect_texts(about.body)
        check("关于弹窗包含加密说明", any("ChaCha20" in t for t in texts))
        about.destroy()

        print("== 账号 / 邮箱 类型区分与互相关联 ==")
        view.reload()
        app.update()

        # 1) 新建邮箱账号
        email_editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        app.update()
        check("新建弹窗默认类型是账号", email_editor.kind == "account")
        email_editor._apply_kind("email")
        app.update()
        check("切到邮箱类型后字段标签变化", str(email_editor._email_label.cget("text")) == "邮箱地址 *")
        check("邮箱类型隐藏用户名栏", str(email_editor.username_row.winfo_ismapped()) == "0")
        email_editor.title_var.set("工作邮箱")
        email_editor.email_var.set("shared@example.com")
        email_editor.password_var.set("mail-pass-1")
        email_editor._save()
        app.update()
        accounts_after = vault.snapshot()["accounts"]
        work_email = next(a for a in accounts_after if a["title"] == "工作邮箱")
        check("邮箱账号保存成功", work_email["kind"] == "email")
        check("邮箱账号分类默认为邮箱", work_email["category"] == "邮箱")
        check("邮箱账号用户名默认为邮箱地址", work_email["username"] == "shared@example.com")
        view.reload()
        app.update()

        # 2) 普通账号填同一邮箱 → 提示并互相关联
        site_editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        site_editor.title_var.set("某个网站")
        site_editor.email_var.set("shared@example.com")
        site_editor.password_var.set("site-pass-1")
        app.update()
        suggest_texts = collect_texts(site_editor.suggest_frame)
        check("检测到已存在的同地址邮箱账号", any("同地址的邮箱账号" in t for t in suggest_texts), str(suggest_texts))
        site_editor._save()
        app.update()
        site = next(a for a in vault.snapshot()["accounts"] if a["title"] == "某个网站")
        check("普通账号类型正确", site["kind"] == "account")
        links_after = vault.snapshot()["links"]
        check(
            "普通账号与邮箱账号自动互相关联",
            any(l["a_id"] == site["id"] and l["b_id"] == work_email["id"] and l["relation"] == "绑定邮箱" for l in links_after),
            str([(l["relation"], l["a_id"], l["b_id"]) for l in links_after]),
        )
        view.reload()
        app.update()

        # 3) 没有对应邮箱账号时，可勾选"一并创建邮箱账号并互相关联"
        new_site_editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        new_site_editor.title_var.set("另一个网站")
        new_site_editor.email_var.set("fresh-mail@example.com")
        new_site_editor.password_var.set("site-pass-2")
        app.update()
        check("提供创建邮箱账号选项", new_site_editor._create_email_var is not None)
        new_site_editor._save()
        app.update()
        snapshot = vault.snapshot()
        created_email = next(
            (a for a in snapshot["accounts"] if a["email"] == "fresh-mail@example.com" and a["kind"] == "email"),
            None,
        )
        check("勾选后自动创建了邮箱账号", created_email is not None, str([(a["title"], a["kind"]) for a in snapshot["accounts"]]))
        site2 = next(a for a in snapshot["accounts"] if a["title"] == "另一个网站")
        check(
            "新账号与新邮箱账号已建立关联",
            any(l["a_id"] == site2["id"] and l["b_id"] == created_email["id"] for l in snapshot["links"]),
        )

        # 4) 新建邮箱账号时，自动把使用该邮箱的普通账号关联进来
        user_site = vault.create_account(
            {"title": "用邮箱登录的站点", "username": "user@example.org", "password": "x"}
        )
        view.reload()
        app.update()
        reverse_editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        reverse_editor._apply_kind("email")
        reverse_editor.title_var.set("Example 邮箱")
        reverse_editor.email_var.set("user@example.org")
        reverse_editor.password_var.set("mail-pass-2")
        app.update()
        reverse_texts = collect_texts(reverse_editor.suggest_frame)
        check('邮箱视角提示正在使用该邮箱的账号', any("使用这个邮箱" in t for t in reverse_texts), str(reverse_texts))
        reverse_editor._save()
        app.update()
        snapshot = vault.snapshot()
        example_email = next(a for a in snapshot["accounts"] if a["title"] == "Example 邮箱")
        check(
            "邮箱账号与使用它的账号反向关联",
            any(
                l["a_id"] == user_site["id"] and l["b_id"] == example_email["id"] and l["relation"] == "绑定邮箱"
                for l in snapshot["links"]
            ),
        )

        # 5) 侧栏类型筛选 + 列表类型标记
        view.reload()
        app.update()
        view.set_filter("kind", "email")
        app.update()
        check("侧栏类型筛选：只剩邮箱账号", len(view._rows) > 0 and all(a["kind"] == "email" for a in view._filtered()))
        row_texts = collect_texts(view.list_scroll.inner)
        check("列表中有「邮箱」类型标记", "邮箱" in row_texts, str(row_texts))

        view.select(example_email["id"])
        app.update()
        detail_texts = collect_texts(view.detail_scroll.inner)
        check("详情显示类型徽章", "邮箱账号" in detail_texts, str(detail_texts[:15]))
        check("邮箱账号详情用「邮箱地址」标签", "邮箱地址" in detail_texts)

        view.set_filter("all")
        app.update()

        print("== 邮箱后缀 → 登录网址 ==")
        auto_editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        auto_editor.email_var.set("someone@gmail.com")
        app.update()
        check("输入 Gmail 自动带出登录网址", auto_editor.url_var.get() == "https://mail.google.com", auto_editor.url_var.get())
        check(
            "提示说明已自动填写",
            "自动填写" in str(auto_editor._url_hint.cget("text")),
            str(auto_editor._url_hint.cget("text")),
        )

        auto_editor.url_var.set("https://my-custom.example/login")
        auto_editor.email_var.set("other@163.com")
        app.update()
        check("用户手动填写的网址不被覆盖", auto_editor.url_var.get() == "https://my-custom.example/login")
        check("提示提供一键替换", "点此替换" in str(auto_editor._url_hint.cget("text")), str(auto_editor._url_hint.cget("text")))
        auto_editor._use_auto_url("https://mail.163.com")
        check("替换后使用 163 登录页", auto_editor.url_var.get() == "https://mail.163.com")

        auto_editor.email_var.set("someone@unknown-provider.example")
        app.update()
        check("无法识别的后缀会清掉自动填入", auto_editor.url_var.get() == "", auto_editor.url_var.get())
        auto_editor.destroy()

        site_no_url = vault.create_account(
            {"title": "QQ 登录的站点", "email": "12345@qq.com", "password": "p"}
        )
        view.reload(select_id=site_no_url["id"])
        app.update()
        detail_texts = collect_texts(view.detail_scroll.inner)
        check("详情按邮箱后缀给出登录页入口", any("QQ 邮箱 登录页" in t for t in detail_texts), str(detail_texts[:12]))
        check("详情显示派生登录页行", "登录页" in detail_texts)

        print("== 「账号就是邮箱地址」的录入 ==")
        view.reload()
        app.update()
        mail_editor = AccountEditorDialog(app, vault, view.accounts, view.links)
        app.update()
        check("默认未勾选「账号就是邮箱」", not mail_editor._account_is_email_var.get())
        mail_editor.title_var.set("网易云音乐")
        mail_editor.email_var.set("shared@example.com")
        app.update()
        check(
            "弹窗说明密码分开保存",
            any("密码" in t and "分开" in t for t in collect_texts(mail_editor.username_row)),
            str(collect_texts(mail_editor.username_row)),
        )
        mail_editor._account_is_email_var.set(True)
        mail_editor._sync_username_from_email()
        check(
            "勾选后用户名自动同步为邮箱",
            mail_editor.username_var.get() == "shared@example.com",
            mail_editor.username_var.get(),
        )
        mail_editor.email_var.set("another@example.com")
        app.update()
        check("改邮箱时用户名跟随同步", mail_editor.username_var.get() == "another@example.com")
        mail_editor._account_is_email_var.set(False)
        mail_editor.email_var.set("third@example.com")
        app.update()
        check("取消勾选后不再同步", mail_editor.username_var.get() == "another@example.com")
        mail_editor._account_is_email_var.set(True)
        mail_editor.email_var.set("shared@example.com")
        mail_editor.password_var.set("mail-login-pw")
        app.update()
        mail_editor._save()
        app.update()
        saved_site = next(a for a in vault.snapshot()["accounts"] if a["title"] == "网易云音乐")
        check("保存后用户名就是邮箱地址", saved_site["username"] == "shared@example.com")
        check("类型仍是普通账号", saved_site["kind"] == "account")
        check(
            "自动关联到同地址邮箱账号",
            any(
                l["a_id"] == saved_site["id"]
                and l["b_id"] == work_email["id"]
                and l["relation"] == "绑定邮箱"
                for l in vault.snapshot()["links"]
            ),
        )
        view.reload()
        app.update()
        reopen = AccountEditorDialog(app, vault, view.accounts, view.links, saved_site)
        app.update()
        check("编辑时自动勾选「账号就是邮箱」", reopen._account_is_email_var.get() is True)
        reopen.destroy()

        # 关联账号的密码各自独立，可直接复制对方的
        view.select(saved_site["id"])
        app.update()
        check("详情里有「复制密码」按钮", "复制密码" in collect_buttons(view.detail_scroll.inner), str(collect_buttons(view.detail_scroll.inner)))
        view._copy_related(work_email)
        app.update()
        try:
            clip = app.clipboard_get()
        except tk.TclError:
            clip = ""
        check("复制到的是邮箱账号自己的密码", clip == "mail-pass-1", repr(clip))
        check("提示里说明是谁的密码", "工作邮箱" in str(view._toast.cget("text")), str(view._toast.cget("text")))

        print("== 账号组 ==")
        view.reload()
        app.update()
        member_a = view.accounts[0]
        member_b = view.accounts[1]
        total_accounts = len(view.accounts)
        game_group = vault.create_group(
            "Apex 游戏组", "EA + Steam + 邮箱", [member_a["id"], member_b["id"]]
        )
        view.reload()
        app.update()

        items = view._visible_items()
        group_items = [item for item in items if item[0] == "group"]
        check("列表里账号组只占一行", len(group_items) == 1)
        check(
            "组成员不再单独占行",
            len(view._rows) == total_accounts - 2,
            f"{len(view._rows)} vs {total_accounts - 2}",
        )
        row_texts = collect_texts(view.list_scroll.inner)
        check("组行显示组名", "Apex 游戏组" in row_texts, str(row_texts[:8]))
        check("组行显示成员数量", any("2 个账号" in t for t in row_texts))

        view._toggle_group(game_group["id"])
        app.update()
        check("展开后成员显示在组下", len(view._rows) == total_accounts, str(len(view._rows)))
        view._toggle_group(game_group["id"])
        app.update()
        check("再次点击收起", len(view._rows) == total_accounts - 2)

        view.select_group(game_group["id"])
        app.update()
        detail_texts = collect_texts(view.detail_scroll.inner)
        check("组详情显示组名", "Apex 游戏组" in detail_texts)
        check("组详情列出成员", member_a["title"] in detail_texts and member_b["title"] in detail_texts)
        check("组详情有复制密码按钮", "复制密码" in collect_buttons(view.detail_scroll.inner))
        view.copy(member_a["password"], f"「{member_a['title']}」的密码")
        app.update()
        try:
            clip = app.clipboard_get()
        except tk.TclError:
            clip = ""
        check("可以复制组内成员的密码", clip == member_a["password"], repr(clip))

        view.search.delete(0, "end")
        view.search.insert(0, member_a["title"])
        view._on_search()
        app.update()
        search_items = view._visible_items()
        check(
            "搜索时展开为平铺结果",
            all(item[0] == "account" for item in search_items)
            and any(item[1]["id"] == member_a["id"] for item in search_items),
            str([i[0] for i in search_items]),
        )
        view.search.delete(0, "end")
        view._on_search()
        app.update()

        vault.update_group(game_group["id"], name="Apex 全家桶", member_ids=[member_a["id"]])
        view.reload()
        app.update()
        row_texts = collect_texts(view.list_scroll.inner)
        check("改名后组行更新", "Apex 全家桶" in row_texts)
        check("减少成员后组行数量更新", any("1 个账号" in t for t in row_texts))

        vault.delete_group(game_group["id"])
        view.reload()
        app.update()
        check("删除组后不再有组行", all(item[0] == "account" for item in view._visible_items()))
        check("账号本身仍然存在", any(a["id"] == member_a["id"] for a in view.accounts))

        print("== 检测更新 ==")
        from pm.gui_dialogs import UpdateDialog

        update_dialog = UpdateDialog(app, "1.1.0", app, auto_check=False)
        app.update()
        update_dialog._on_manifest(
            {"version": "1.1.0", "notes": [], "download_url": "https://example.com/1.1.0.zip"}
        )
        app.update()
        check(
            "已是最新版本提示",
            "最新" in str(update_dialog.status.cget("text")),
            str(update_dialog.status.cget("text")),
        )
        check("最新时没有下载按钮", not update_dialog.action_btn.winfo_manager())

        update_dialog._on_manifest(
            {
                "version": "1.2.0",
                "notes": ["新增检测更新"],
                "download_url": "https://example.com/1.2.0.zip",
            }
        )
        app.update()
        check("提示发现新版本", "1.2.0" in str(update_dialog.status.cget("text")))
        check("出现下载并更新按钮", bool(update_dialog.action_btn.winfo_manager()))
        check("显示更新说明", "新增检测更新" in update_dialog.notes.get("1.0", "end"))

        update_dialog._on_error("检测失败：网络错误")
        app.update()
        check("检测失败提示", "失败" in str(update_dialog.status.cget("text")))
        check("失败时出现重试按钮", bool(update_dialog.retry_btn.winfo_manager()))
        update_dialog.destroy()

        print("== 自动加密备份与恢复 ==")
        backup_files = sorted(app.backup_dir.glob("vault-*.db"))
        check("解锁时自动生成加密备份", len(backup_files) >= 1, str([p.name for p in backup_files]))
        check("备份文件能被识别为密码库", store.looks_like_vault(backup_files[-1]))
        check("能定位到最新备份", app._latest_backup() is not None)

        app.auth_view.show_restore_offer(backup_files[-1])
        app.update()
        check("能显示备份恢复提示条", bool(app.auth_view.restore_banner.winfo_manager()))
        banner_texts = collect_texts(app.auth_view.restore_banner)
        check("恢复提示包含备份时间与按钮", any("最近一次" in t for t in banner_texts) and any("恢复" in t for t in banner_texts), str(banner_texts))
        app.auth_view.hide_restore_offer()
        check("可以隐藏恢复提示", not app.auth_view.restore_banner.winfo_manager())

        # 模拟数据文件被删后，从备份恢复
        app._replace_with_backup(backup_files[-1])
        app.update()
        check("恢复后回到解锁界面", app.auth_view.mode == "unlock")
        app.auth_view.password_var.set(NEW_PASSWORD)
        app.auth_view._submit()
        app.update()
        check("恢复后可用原密码解锁", app.vault_view.winfo_ismapped())
        check("恢复后数据仍在", len(app.vault_view.accounts) >= 1, str(len(app.vault_view.accounts)))

        check("界面回调无异常", not tk_errors, str(tk_errors))
    finally:
        try:
            app.vault.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass

    print()
    if failures:
        print(f"❌ {len(failures)} 项失败：" + "、".join(failures))
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
