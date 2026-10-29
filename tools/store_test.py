"""数据层自检：直接驱动 ``pm.store.Vault``，不涉及界面。

用法::

    python tools/store_test.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm import crypto  # noqa: E402
from pm import update  # noqa: E402
from pm import util  # noqa: E402
from pm.store import (  # noqa: E402
    BadPassword,
    InvalidInput,
    Vault,
    VaultError,
    VaultLocked,
    looks_like_vault,
)

PASSWORD = "correct horse 电池 订书钉"
NEW_PASSWORD = "another Strong Passphrase 42!"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [ok] {name}")
    else:
        failures.append(name)
        print(f"  [FAIL] {name} {detail}")


def main() -> int:
    workspace = Path(__file__).resolve().parent.parent
    tmp = workspace / ".tmp" / "store"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    db_path = tmp / "vault.db"

    vault = Vault(db_path, idle_timeout=900)

    print("== 初始化 ==")
    check("新库未初始化", vault.initialized is False and vault.unlocked is False)

    try:
        vault.initialize("123")
        check("过短主密码被拒绝", False)
    except InvalidInput as exc:
        check("过短主密码被拒绝", "8" in str(exc))

    vault.initialize(PASSWORD)
    check("初始化后处于解锁状态", vault.initialized is True and vault.unlocked is True)
    snapshot = vault.snapshot()
    check("新库为空", snapshot["accounts"] == [] and snapshot["links"] == [])

    print("== 账号 CRUD ==")
    github = vault.create_account(
        {
            "title": "GitHub",
            "username": "octocat",
            "email": "octocat@gmail.com",
            "password": "S3cr3t-Unique-值-7788",
            "url": "https://github.com/login",
            "category": "开发",
            "tags": ["工作", "常用", "工作"],
            "notes": "已开启两步验证 🔐\n恢复码在保险箱",
            "favorite": False,
        }
    )
    check("创建账号返回 id", isinstance(github["id"], int) and github["id"] > 0)
    check("标签已去重", github["tags"] == ["工作", "常用"], str(github["tags"]))
    check("备注保留换行与 emoji", "🔐" in github["notes"] and "\n" in github["notes"])

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

    try:
        vault.create_account({"title": "   "})
        check("空名称被拒绝", False)
    except InvalidInput:
        check("空名称被拒绝", True)

    try:
        vault.create_account({"title": "只有标题"})
        check("无有效字段的账号被拒绝", False)
    except InvalidInput:
        check("无有效字段的账号被拒绝", True)

    try:
        vault.create_account({"title": "超长", "username": "x", "password": "y" * 2000})
        check("超长密码被拒绝", False)
    except InvalidInput:
        check("超长密码被拒绝", True)

    updated = vault.update_account(github["id"], {"favorite": True, "category": "开发工具"})
    check("更新收藏与分类", updated["favorite"] is True and updated["category"] == "开发工具")
    check(
        "更新保留其他字段",
        updated["username"] == "octocat" and updated["password"] == "S3cr3t-Unique-值-7788",
    )
    check("created 时间未被改写", updated["created"] == github["created"])

    try:
        vault.update_account(99999, {"favorite": True})
        check("更新不存在的账号被拒绝", False)
    except VaultError:
        check("更新不存在的账号被拒绝", True)

    print("== 账号关联 ==")
    link = vault.create_link(github["id"], gmail["id"], "绑定邮箱")
    check("建立「绑定邮箱」关联", link["relation"] == "绑定邮箱" and link["a_id"] == github["id"])

    try:
        vault.create_link(github["id"], gmail["id"], "绑定邮箱")
        check("重复关联被拒绝", False)
    except InvalidInput:
        check("重复关联被拒绝", True)

    try:
        vault.create_link(github["id"], github["id"], "关联")
        check("自关联被拒绝", False)
    except InvalidInput:
        check("自关联被拒绝", True)

    try:
        vault.create_link(github["id"], 424242, "关联")
        check("关联不存在的账号被拒绝", False)
    except InvalidInput:
        check("关联不存在的账号被拒绝", True)

    reverse = vault.create_link(gmail["id"], github["id"], "主账号")
    extra = vault.create_account({"title": "Steam", "username": "gamer", "password": "p"})
    vault.create_link(gmail["id"], extra["id"], "两步验证")

    snapshot = vault.snapshot()
    check("快照包含 3 个账号 / 3 条关联", len(snapshot["accounts"]) == 3 and len(snapshot["links"]) == 3)
    check("关联按 id 排序稳定", [l["id"] for l in snapshot["links"]] == sorted(l["id"] for l in snapshot["links"]))

    print("== 删除与级联 ==")
    vault.delete_link(reverse["id"])
    check("删除单条关联", len(vault.snapshot()["links"]) == 2)

    vault.delete_account(extra["id"])
    snapshot = vault.snapshot()
    check("删除账号", len(snapshot["accounts"]) == 2)
    check("关联按外键级联清理", len(snapshot["links"]) == 1, str(snapshot["links"]))

    try:
        vault.delete_account(extra["id"])
        check("重复删除被拒绝", False)
    except VaultError:
        check("重复删除被拒绝", True)

    print("== 锁定 / 解锁 ==")
    vault.lock()
    check("锁定后 cleared", vault.unlocked is False)
    try:
        vault.snapshot()
        check("锁定后读取被拒绝", False)
    except VaultLocked:
        check("锁定后读取被拒绝", True)

    for _ in range(4):
        try:
            vault.unlock("错误的密码")
        except BadPassword:
            pass
    try:
        vault.unlock(PASSWORD)
        check("正确主密码解锁", vault.unlocked is True)
    except BadPassword:
        check("正确主密码解锁", False)

    check("解锁后数据完整", len(vault.snapshot()["accounts"]) == 2)

    print("== 失败次数冷却 ==")
    vault.lock()
    vault._conn.execute("UPDATE meta SET v = '10' WHERE k = 'auth_fail'")
    vault._conn.execute("UPDATE meta SET v = ? WHERE k = 'auth_until'", (str(time.time() + 30),))
    vault._conn.commit()
    try:
        vault.unlock(PASSWORD)
        check("冷却期内拒绝解锁", False)
    except BadPassword as exc:
        check("冷却期内拒绝解锁", exc.retry_after > 0, str(exc))
    vault._conn.execute("UPDATE meta SET v = '0' WHERE k = 'auth_fail'")
    vault._conn.execute("UPDATE meta SET v = '0' WHERE k = 'auth_until'")
    vault._conn.commit()
    vault.unlock(PASSWORD)

    print("== 空闲锁定 ==")
    original_timeout = vault.idle_timeout
    vault.idle_timeout = -1
    check("超时判定为过期", vault.idle_expired() is True)
    vault.touch()
    vault.idle_timeout = original_timeout
    check("touch 后不过期", vault.idle_expired() is False)

    print("== 修改主密码 ==")
    try:
        vault.change_password("错误的原密码", NEW_PASSWORD)
        check("原密码错误时拒绝修改", False)
    except BadPassword:
        check("原密码错误时拒绝修改", True)

    try:
        vault.change_password(PASSWORD, "short")
        check("新密码太短被拒绝", False)
    except InvalidInput:
        check("新密码太短被拒绝", True)

    vault.change_password(PASSWORD, NEW_PASSWORD)
    vault.lock()
    try:
        vault.unlock(PASSWORD)
        check("旧主密码失效", False)
    except BadPassword:
        check("旧主密码失效", True)
    vault.unlock(NEW_PASSWORD)
    snapshot = vault.snapshot()
    check("新主密码可解锁且数据完好", snapshot["accounts"][0]["title"] == "GitHub")

    print("== 导出 ==")
    export = vault.export_plain()
    check("导出包含明文密码", export["accounts"][0]["password"] == "S3cr3t-Unique-值-7788")
    check("导出含关联信息", len(export["links"]) == 1)
    check("导出可被 JSON 序列化", isinstance(json.dumps(export, ensure_ascii=False), str))

    print("== 磁盘上无明文 ==")
    vault.close()
    blobs = b""
    for candidate in (db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
        if candidate.exists():
            blobs += candidate.read_bytes()
    check("标题不以明文落盘", "GitHub".encode() not in blobs)
    check("密码不以明文落盘", "S3cr3t-Unique-值-7788".encode() not in blobs)
    check("邮箱不以明文落盘", b"octocat@gmail.com" not in blobs)
    check("备注不以明文落盘", "恢复码".encode() not in blobs)

    print("== 重新打开数据库（持久化）==")
    reopened = Vault(db_path, idle_timeout=900)
    check("重新打开后需要解锁", reopened.initialized is True and reopened.unlocked is False)
    reopened.unlock(NEW_PASSWORD)
    snapshot = reopened.snapshot()
    check("重启后数据仍完整", len(snapshot["accounts"]) == 2 and len(snapshot["links"]) == 1)
    check("重启后密码可解密", snapshot["accounts"][0]["password"] == "S3cr3t-Unique-值-7788")
    reopened.close()

    print("== 账号 / 邮箱 类型区分 ==")
    db2 = tmp / "vault2.db"
    typed = Vault(db2, idle_timeout=900)
    typed.initialize(PASSWORD)
    plain = typed.create_account({"title": "GitHub", "username": "octocat", "password": "x"})
    check("默认类型是普通账号", plain["kind"] == "account", plain["kind"])

    email_acc = typed.create_account(
        {"title": "工作邮箱", "kind": "email", "email": "octocat@gmail.com"}
    )
    check("邮箱账号只需邮箱地址即可", email_acc["kind"] == "email")
    check("邮箱账号默认归入「邮箱」分类", email_acc["category"] == "邮箱", email_acc["category"])

    try:
        typed.create_account({"title": "坏邮箱", "kind": "email", "username": "x"})
        check("邮箱账号缺少邮箱地址被拒绝", False)
    except InvalidInput:
        check("邮箱账号缺少邮箱地址被拒绝", True)

    try:
        typed.create_account({"title": "坏类型", "kind": "bogus", "username": "x", "password": "y"})
        check("非法账号类型被拒绝", False)
    except InvalidInput:
        check("非法账号类型被拒绝", True)

    updated_kind = typed.update_account(plain["id"], {"kind": "email", "email": "octocat@gmail.com"})
    check("可以把普通账号改成邮箱账号", updated_kind["kind"] == "email")

    link = typed.create_link(email_acc["id"], plain["id"], "绑定邮箱")
    check("邮箱账号可与普通账号互相关联", link["a_id"] == email_acc["id"] and link["b_id"] == plain["id"])

    exported = typed.export_plain()
    expected_kinds = {a["id"]: a["kind"] for a in typed.snapshot()["accounts"]}
    check(
        "导出包含类型字段",
        {a["id"]: a["kind"] for a in exported["accounts"]} == expected_kinds
        and set(expected_kinds.values()) <= {"account", "email"},
        str([(a["title"], a["kind"]) for a in exported["accounts"]]),
    )

    print("== 加密备份 ==")
    backup_dir = tmp / "backups"
    first_backup = typed.backup(backup_dir, keep=3)
    check("生成加密备份文件", first_backup.exists() and first_backup.stat().st_size > 0)
    for _ in range(4):
        typed.backup(backup_dir, keep=3)
    files = sorted(backup_dir.glob("vault-*.db"))
    check("备份轮转只保留最近 3 份", len(files) == 3, str([f.name for f in files]))
    check("备份文件能被识别为密码库", looks_like_vault(files[-1]))

    restored = Vault(files[-1], idle_timeout=900)
    restored.unlock(PASSWORD)
    check("备份可独立解锁", restored.unlocked)
    check("备份内数据完整", len(restored.snapshot()["accounts"]) == 2)
    restored.close()
    typed.close()

    print("== 邮箱后缀 → 登录网址 ==")
    check(
        "Gmail 识别",
        util.lookup_email_provider("Someone@Gmail.com") == ("Gmail", "https://mail.google.com"),
    )
    check("QQ 邮箱识别", util.lookup_email_provider("123456@qq.com")[1] == "https://mail.qq.com")
    check("子域名也能识别", util.lookup_email_provider("a@mail.qq.com")[1] == "https://mail.qq.com")
    check("163 邮箱识别", util.lookup_email_provider("a@163.com")[1] == "https://mail.163.com")
    check("未知后缀返回 None", util.lookup_email_provider("a@unknown-provider.example") is None)
    check("非邮箱返回 None", util.lookup_email_provider("not-an-email") is None)
    check(
        "网址归一化后比较",
        util.normalize_url("HTTPS://Mail.QQ.com/") == util.normalize_url("https://mail.qq.com"),
    )

    print("== 账号组 ==")
    db3 = tmp / "vault3.db"
    grouped = Vault(db3, idle_timeout=900)
    grouped.initialize(PASSWORD)
    apex = grouped.create_account({"title": "Apex", "username": "apex-user", "password": "p1"})
    ea = grouped.create_account({"title": "EA", "username": "ea-user", "password": "p2"})
    steam = grouped.create_account({"title": "Steam", "username": "steam-user", "password": "p3"})

    game_group = grouped.create_group("Apex 游戏组", "EA + Steam + 邮箱", [apex["id"], ea["id"], steam["id"]])
    check(
        "创建账号组",
        game_group["name"] == "Apex 游戏组" and game_group["member_ids"] == [apex["id"], ea["id"], steam["id"]],
    )
    check("快照里包含账号组", any(g["id"] == game_group["id"] for g in grouped.snapshot()["groups"]))

    renamed = grouped.update_group(
        game_group["id"], name="Apex 全家桶", member_ids=[apex["id"], ea["id"]]
    )
    check("更新组名与成员", renamed["name"] == "Apex 全家桶" and renamed["member_ids"] == [apex["id"], ea["id"]])

    try:
        grouped.create_group("坏组", member_ids=[99999])
        check("成员必须是已存在账号", False)
    except InvalidInput:
        check("成员必须是已存在账号", True)

    try:
        grouped.create_group("   ")
        check("空组名被拒绝", False)
    except InvalidInput:
        check("空组名被拒绝", True)

    grouped.delete_account(ea["id"])
    current = next(g for g in grouped.snapshot()["groups"] if g["id"] == game_group["id"])
    check("删除账号后自动移出账号组", current["member_ids"] == [apex["id"]], str(current["member_ids"]))

    grouped.delete_group(game_group["id"])
    final = grouped.snapshot()
    check("删除账号组后账号仍在", {a["title"] for a in final["accounts"]} == {"Apex", "Steam"})
    check("账号组列表清空", final["groups"] == [])
    grouped.close()

    group_blobs = b""
    for candidate in (db3, db3.with_name(db3.name + "-wal"), db3.with_name(db3.name + "-shm")):
        if candidate.exists():
            group_blobs += candidate.read_bytes()
    check("账号组名称不以明文落盘", "Apex 游戏组".encode() not in group_blobs)
    check("账号组备注不以明文落盘", "EA + Steam".encode() not in group_blobs)

    print("== 在线更新 ==")
    check(
        "版本号解析",
        update.parse_version("v1.2.3") == (1, 2, 3)
        and update.parse_version("1.10.0") > update.parse_version("1.9.9"),
    )
    check(
        "新版本判断",
        update.is_newer("1.2.0", "1.1.0") and not update.is_newer("1.1.0", "1.1.0"),
    )

    release_root = tmp / "release" / "PasswordManager-9.9.9"
    (release_root / "pm").mkdir(parents=True)
    (release_root / "pm" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (release_root / "pm" / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    (release_root / "app.py").write_text("print('new')\n", encoding="utf-8")
    (release_root / "version.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
    release_zip = tmp / "release.zip"
    with zipfile.ZipFile(release_zip, "w") as archive:
        for path in release_root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(release_root.parent).as_posix())

    app_dir = tmp / "appdir"
    (app_dir / "pm").mkdir(parents=True)
    (app_dir / "tools").mkdir(parents=True)
    (app_dir / "data").mkdir(parents=True)
    (app_dir / "data" / "vault.db").write_text("secret", encoding="utf-8")
    (app_dir / "pm" / "__init__.py").write_text('__version__ = "9.0.0"\n', encoding="utf-8")
    (app_dir / "pm" / "stale_old.py").write_text("old = 1\n", encoding="utf-8")
    (app_dir / "tools" / "old_tool.py").write_text("x\n", encoding="utf-8")
    (app_dir / "app.py").write_text("print('old')\n", encoding="utf-8")

    backup = update.apply_update(release_zip, app_dir)
    check("更新后 app.py 被替换", (app_dir / "app.py").read_text(encoding="utf-8") == "print('new')\n")
    check("更新后版本号变新", "9.9.9" in (app_dir / "pm" / "__init__.py").read_text(encoding="utf-8"))
    check("新模块已写入", (app_dir / "pm" / "new_module.py").exists())
    check(
        "旧版本遗留文件被清理",
        not (app_dir / "pm" / "stale_old.py").exists()
        and not (app_dir / "tools" / "old_tool.py").exists(),
    )
    check("data 目录未被触碰", (app_dir / "data" / "vault.db").read_text(encoding="utf-8") == "secret")
    check("已生成程序文件备份", backup.exists() and backup.parent.name == "backups")

    update.restore_program_files(backup, app_dir)
    check(
        "可用备份回滚",
        '__version__ = "9.0.0"' in (app_dir / "pm" / "__init__.py").read_text(encoding="utf-8"),
    )

    print("== 加密原语冒烟 ==")
    key = crypto.random_bytes(crypto.KEY_SIZE)
    blob = crypto.encrypt(key, "hello 世界".encode("utf-8"), aad=b"x")
    check("AEAD 加解密一致", crypto.decrypt(key, blob, aad=b"x") == "hello 世界".encode("utf-8"))
    tampered = bytearray(blob)
    tampered[-1] ^= 0xFF
    try:
        crypto.decrypt(key, bytes(tampered), aad=b"x")
        check("篡改被发现", False)
    except crypto.CipherError:
        check("篡改被发现", True)

    print()
    if failures:
        print(f"❌ {len(failures)} 项失败：" + "、".join(failures))
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
