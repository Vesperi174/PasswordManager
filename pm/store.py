"""数据层：SQLite 存储 + 逐条加密 + 账号关联关系。

设计要点
--------
* 整个库只有一个文件（``data/vault.db``），SQLite 自带、无需安装数据库服务。
* **每个账号是一条加密记录**：``accounts.payload`` 是 ChaCha20-Poly1305 密文，
  明文只存在于内存中已解锁的进程里。标题、网址、备注等同样加密，不留明文。
* 开启后（``unlock``）一次性解密进内存，之后的增删改只重写受影响的那一行。
* ``links`` 表记录账号之间的绑定关系（如"绑定邮箱""主账号/子账号"），
  删除账号时通过外键 ``ON DELETE CASCADE`` 自动清理相关关联。
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import crypto

SCHEMA_VERSION = 1
SALT_SIZE = 16
AAD_VERIFIER = b"pm/vault/verifier/v1"
AAD_ACCOUNT = b"pm/vault/account/v1"
AAD_GROUP = b"pm/vault/group/v1"
_VERIFIER_TOKEN = b"pm-vault-ok"

MAX_ATTEMPTS_BEFORE_LOCKOUT = 5
LOCKOUT_BASE_SECONDS = 5
LOCKOUT_MAX_SECONDS = 300

TEXT_LIMITS = {
    "title": 200,
    "username": 256,
    "email": 320,
    "password": 1024,
    "url": 2000,
    "category": 40,
    "notes": 20000,
    "group_name": 60,
    "group_note": 20000,
}
MAX_TAGS = 20
MAX_TAG_LENGTH = 32
MAX_RELATION_LENGTH = 60

ACCOUNT_FIELDS = (
    "title",
    "kind",
    "username",
    "email",
    "password",
    "url",
    "category",
    "tags",
    "notes",
    "favorite",
)

#: 账号类型：普通登录账号 / 邮箱（用来被普通账号"绑定邮箱"）
KINDS = {"account", "email"}
KIND_LABELS = {"account": "账号", "email": "邮箱账号"}
DEFAULT_KIND = "account"


class VaultError(Exception):
    """数据层通用错误，``str(err)`` 可直接展示给用户。"""


class VaultLocked(VaultError):
    """库处于锁定状态。"""


class BadPassword(VaultError):
    """主密码错误或尝试过于频繁。"""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InvalidInput(VaultError):
    """提交的数据不合法。"""


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _clean_text(value: Any, field: str, *, strip: bool = True) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidInput(f"字段 {field} 必须是文本")
    value = value.replace("\x00", "")
    if strip:
        value = value.strip()
    limit = TEXT_LIMITS.get(field)
    if limit is not None and len(value) > limit:
        raise InvalidInput(f"字段 {field} 过长（最多 {limit} 个字符）")
    return value


def _clean_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part for part in value.replace("，", ",").split(",")]
    if not isinstance(value, list):
        raise InvalidInput("标签格式不正确")
    tags: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise InvalidInput("标签必须是文本")
        tag = raw.replace(",", "").replace("，", "").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise InvalidInput(f"单个标签最多 {MAX_TAG_LENGTH} 个字符")
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise InvalidInput(f"最多 {MAX_TAGS} 个标签")
    return tags


def looks_like_vault(path: str | os.PathLike[str]) -> bool:
    """粗略判断一个文件是不是本程序的密码库（能只读打开且 meta 表里有 salt）。"""
    target = Path(path)
    try:
        con = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = con.execute("SELECT 1 FROM meta WHERE k = 'salt'").fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


class Vault:
    """密码库。

    实例内部持有一把内存中的数据密钥与已解密的账号缓存；``lock()`` 会清空它们。
    所有公开方法都是线程安全的（内部 ``RLock``）。
    """
    def __init__(self, db_path: str | os.PathLike[str], *, idle_timeout: float = 900.0) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.idle_timeout = float(idle_timeout)

        self._mu = threading.RLock()
        self._key: bytes | None = None
        self._accounts: dict[int, dict[str, Any]] = {}
        self._links: dict[int, dict[str, Any]] = {}
        self._groups: dict[int, dict[str, Any]] = {}
        self._last_activity = time.time()

        self._conn = sqlite3.connect(
            str(self.db_path), timeout=10.0, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ------------------------------------------------------------------ #
    # 基础设施
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload    BLOB    NOT NULL,
                    created_at REAL    NOT NULL,
                    updated_at REAL    NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    a_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    b_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    relation   TEXT    NOT NULL DEFAULT '',
                    created_at REAL    NOT NULL,
                    UNIQUE (a_id, b_id, relation),
                    CHECK (a_id <> b_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_links_a ON links(a_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_links_b ON links(b_id)"
            )
            # 账号组：把多个账号打包展示（如一个游戏需要 Apex + EA + Steam + 邮箱）
            # 组名与备注同样加密后存进 payload，不落明文
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload    BLOB    NOT NULL,
                    created_at REAL    NOT NULL,
                    updated_at REAL    NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_members (
                    group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    PRIMARY KEY (group_id, account_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_group_members_account ON group_members(account_id)"
            )

    def _meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        return row["v"] if row else default

    def _meta_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, value),
        )

    def _touch(self) -> None:
        self._last_activity = time.time()

    def touch(self) -> None:
        """标记一次活动（用于空闲自动锁定）。"""
        with self._mu:
            self._touch()

    def idle_expired(self) -> bool:
        with self._mu:
            if self._key is None:
                return False
            return (time.time() - self._last_activity) > self.idle_timeout

    def idle_remaining(self) -> float:
        """距离空闲自动锁定还剩多少秒（未解锁时为 0）。"""
        with self._mu:
            if self._key is None:
                return 0.0
            return max(0.0, self.idle_timeout - (time.time() - self._last_activity))

    def close(self) -> None:
        with self._mu:
            self.lock()
            self._conn.close()

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    @property
    def initialized(self) -> bool:
        with self._mu:
            return self._meta_get("salt") is not None

    @property
    def unlocked(self) -> bool:
        with self._mu:
            return self._key is not None

    def _require_unlocked(self) -> None:
        if self._key is None:
            raise VaultLocked("密码库已锁定，请先解锁")

    # ------------------------------------------------------------------ #
    # 初始化 / 解锁 / 锁定
    # ------------------------------------------------------------------ #
    def initialize(self, password: str) -> None:
        """首次使用：创建主密码与空库。"""
        with self._mu:
            if self.initialized:
                raise VaultError("密码库已存在，请直接解锁")
            self._validate_master_password(password)
            salt = crypto.random_bytes(SALT_SIZE)
            iterations = crypto.DEFAULT_ITERATIONS
            key = crypto.derive_key(password, salt, iterations)
            with self._conn:
                self._meta_set("schema_version", str(SCHEMA_VERSION))
                self._meta_set("salt", _b64e(salt))
                self._meta_set("iterations", str(iterations))
                self._meta_set(
                    "verifier", _b64e(crypto.encrypt(key, _VERIFIER_TOKEN, AAD_VERIFIER))
                )
                self._meta_set("created_at", str(time.time()))
                self._meta_set("auth_fail", "0")
                self._meta_set("auth_until", "0")
            self._key = key
            self._accounts = {}
            self._links = {}
            self._touch()

    def unlock(self, password: str) -> None:
        with self._mu:
            salt_b64 = self._meta_get("salt")
            if salt_b64 is None:
                raise VaultError("密码库尚未初始化")
            now = time.time()
            lock_until = float(self._meta_get("auth_until") or 0)
            if now < lock_until:
                wait = lock_until - now
                raise BadPassword(
                    f"密码错误次数过多，请等待 {int(wait) + 1} 秒后再试", retry_after=wait
                )

            iterations = int(self._meta_get("iterations") or crypto.DEFAULT_ITERATIONS)
            key = crypto.derive_key(password, _b64d(salt_b64), iterations)
            verifier_b64 = self._meta_get("verifier") or ""
            try:
                token = crypto.decrypt(key, _b64d(verifier_b64), AAD_VERIFIER)
                ok = token == _VERIFIER_TOKEN
            except crypto.CipherError:
                ok = False

            if not ok:
                fails = int(self._meta_get("auth_fail") or 0) + 1
                with self._conn:
                    self._meta_set("auth_fail", str(fails))
                    if fails >= MAX_ATTEMPTS_BEFORE_LOCKOUT:
                        delay = min(
                            LOCKOUT_MAX_SECONDS,
                            LOCKOUT_BASE_SECONDS * 2 ** (fails - MAX_ATTEMPTS_BEFORE_LOCKOUT),
                        )
                        self._meta_set("auth_until", str(time.time() + delay))
                raise BadPassword("主密码错误")

            with self._conn:
                self._meta_set("auth_fail", "0")
                self._meta_set("auth_until", "0")
            self._key = key
            self._load_all()
            self._touch()

    def lock(self) -> None:
        with self._mu:
            # Python 无法真正擦除不可变 bytes，但这里会尽早丢弃密钥与明文缓存的引用。
            self._key = None
            self._accounts = {}
            self._links = {}
            self._groups = {}

    @staticmethod
    def _validate_master_password(password: str) -> None:
        if not isinstance(password, str):
            raise InvalidInput("主密码格式不正确")
        if len(password) < 8:
            raise InvalidInput("主密码至少需要 8 个字符")
        if len(password) > 1024:
            raise InvalidInput("主密码过长")

    # ------------------------------------------------------------------ #
    # 加解密缓存
    # ------------------------------------------------------------------ #
    def _load_all(self) -> None:
        accounts: dict[int, dict[str, Any]] = {}
        for row in self._conn.execute("SELECT id, payload FROM accounts"):
            accounts[int(row["id"])] = self._decode(row["payload"], int(row["id"]))
        links: dict[int, dict[str, Any]] = {}
        for row in self._conn.execute("SELECT * FROM links"):
            links[int(row["id"])] = {
                "id": int(row["id"]),
                "a_id": int(row["a_id"]),
                "b_id": int(row["b_id"]),
                "relation": row["relation"] or "",
                "created": float(row["created_at"]),
            }
        groups: dict[int, dict[str, Any]] = {}
        for row in self._conn.execute("SELECT id, payload, created_at, updated_at FROM groups"):
            group_id = int(row["id"])
            content = self._decode_group(row["payload"], group_id)
            groups[group_id] = {
                "id": group_id,
                "name": content["name"],
                "note": content["note"],
                "created": float(row["created_at"]),
                "updated": float(row["updated_at"]),
                "member_ids": [],
            }
        for row in self._conn.execute("SELECT group_id, account_id FROM group_members"):
            group = groups.get(int(row["group_id"]))
            if group is not None:
                group["member_ids"].append(int(row["account_id"]))
        self._accounts = accounts
        self._links = links
        self._groups = groups

    def _decode(self, payload: bytes, account_id: int) -> dict[str, Any]:
        assert self._key is not None
        try:
            raw = crypto.decrypt(self._key, payload, AAD_ACCOUNT)
            data = json.loads(raw.decode("utf-8"))
        except (crypto.CipherError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VaultError(f"账号 #{account_id} 解密失败，数据可能已损坏") from exc
        if not isinstance(data, dict):
            raise VaultError(f"账号 #{account_id} 数据格式异常")
        account = {field: data.get(field) for field in ACCOUNT_FIELDS}
        account.update(
            {
                "id": account_id,
                "created": float(data.get("created") or time.time()),
                "updated": float(data.get("updated") or time.time()),
            }
        )
        kind = account.get("kind") or DEFAULT_KIND
        account["kind"] = kind if kind in KINDS else DEFAULT_KIND
        account["tags"] = [str(t) for t in (account.get("tags") or [])][:MAX_TAGS]
        account["favorite"] = bool(account.get("favorite"))
        for text_field, limit in TEXT_LIMITS.items():
            value = account.get(text_field) or ""
            account[text_field] = str(value)[:limit]
        return account

    def _encode(self, account: dict[str, Any], key: bytes | None = None) -> bytes:
        """把一条账号记录序列化并加密。``key`` 缺省使用当前数据密钥。"""
        key = key or self._key
        if key is None:
            raise VaultLocked("密码库已锁定，请先解锁")
        body = {field: account.get(field) for field in ACCOUNT_FIELDS}
        body["created"] = account.get("created", time.time())
        body["updated"] = account.get("updated", time.time())
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return crypto.encrypt(key, raw, AAD_ACCOUNT)

    def _decode_group(self, payload: bytes, group_id: int) -> dict[str, str]:
        assert self._key is not None
        try:
            raw = crypto.decrypt(self._key, payload, AAD_GROUP)
            data = json.loads(raw.decode("utf-8"))
        except (crypto.CipherError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VaultError(f"账号组 #{group_id} 解密失败，数据可能已损坏") from exc
        if not isinstance(data, dict):
            raise VaultError(f"账号组 #{group_id} 数据格式异常")
        return {
            "name": str(data.get("name") or ""),
            "note": str(data.get("note") or ""),
        }

    def _encode_group(self, name: str, note: str, key: bytes | None = None) -> bytes:
        key = key or self._key
        if key is None:
            raise VaultLocked("密码库已锁定，请先解锁")
        raw = json.dumps({"name": name, "note": note}, ensure_ascii=False).encode("utf-8")
        return crypto.encrypt(key, raw, AAD_GROUP)

    # ------------------------------------------------------------------ #
    # 账号 CRUD
    # ------------------------------------------------------------------ #
    @staticmethod
    def _prepare(data: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise InvalidInput("提交的数据格式不正确")
        merged: dict[str, Any] = dict(existing or {})
        merged.update({k: v for k, v in data.items() if k in ACCOUNT_FIELDS})

        cleaned = {field: _clean_text(merged.get(field), field) for field in TEXT_LIMITS}
        cleaned["notes"] = _clean_text(merged.get("notes"), "notes", strip=False).strip()
        cleaned["tags"] = _clean_tags(merged.get("tags"))
        favorite = merged.get("favorite", False)
        cleaned["favorite"] = favorite if isinstance(favorite, bool) else str(favorite).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        kind = merged.get("kind") or DEFAULT_KIND
        if kind not in KINDS:
            raise InvalidInput("账号类型只能是「账号」或「邮箱账号」")
        cleaned["kind"] = kind
        if kind == "email":
            if not cleaned["email"]:
                raise InvalidInput("邮箱账号请填写邮箱地址")
            if not cleaned["category"]:
                cleaned["category"] = "邮箱"

        if not cleaned["title"]:
            raise InvalidInput("账号名称不能为空")
        if not any(cleaned[f] for f in ("username", "email", "password", "url", "notes")):
            raise InvalidInput("至少填写用户名、邮箱或密码中的一项")
        return cleaned

    @staticmethod
    def _public(account: dict[str, Any]) -> dict[str, Any]:
        return dict(account)

    def create_account(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._mu:
            self._require_unlocked()
            cleaned = self._prepare(data)
            now = time.time()
            cleaned["created"] = now
            cleaned["updated"] = now
            payload = self._encode(cleaned)
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO accounts (payload, created_at, updated_at) VALUES (?, ?, ?)",
                    (payload, now, now),
                )
                account_id = int(cursor.lastrowid)
            account = self._decode(payload, account_id)
            self._accounts[account_id] = account
            self._touch()
            return self._public(account)

    def update_account(self, account_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with self._mu:
            self._require_unlocked()
            existing = self._accounts.get(int(account_id))
            if existing is None:
                raise VaultError("账号不存在")
            cleaned = self._prepare(data, existing)
            cleaned["created"] = existing["created"]
            cleaned["updated"] = time.time()
            payload = self._encode(cleaned)
            with self._conn:
                self._conn.execute(
                    "UPDATE accounts SET payload = ?, updated_at = ? WHERE id = ?",
                    (payload, cleaned["updated"], int(account_id)),
                )
            account = self._decode(payload, int(account_id))
            self._accounts[int(account_id)] = account
            self._touch()
            return self._public(account)

    def delete_account(self, account_id: int) -> None:
        with self._mu:
            self._require_unlocked()
            account_id = int(account_id)
            if account_id not in self._accounts:
                raise VaultError("账号不存在")
            with self._conn:
                self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            self._accounts.pop(account_id, None)
            for link_id in [
                lid
                for lid, link in self._links.items()
                if link["a_id"] == account_id or link["b_id"] == account_id
            ]:
                self._links.pop(link_id, None)
            for group in self._groups.values():
                if account_id in group["member_ids"]:
                    group["member_ids"] = [aid for aid in group["member_ids"] if aid != account_id]
            self._touch()

    # ------------------------------------------------------------------ #
    # 关联关系
    # ------------------------------------------------------------------ #
    def create_link(self, a_id: int, b_id: int, relation: str = "") -> dict[str, Any]:
        with self._mu:
            self._require_unlocked()
            a_id, b_id = int(a_id), int(b_id)
            if a_id == b_id:
                raise InvalidInput("不能把一个账号关联到它自己")
            if a_id not in self._accounts or b_id not in self._accounts:
                raise InvalidInput("关联的账号不存在")
            relation = _clean_text(relation, "relation") or "关联"
            if len(relation) > MAX_RELATION_LENGTH:
                raise InvalidInput(f"关联类型最多 {MAX_RELATION_LENGTH} 个字符")
            now = time.time()
            try:
                with self._conn:
                    cursor = self._conn.execute(
                        "INSERT INTO links (a_id, b_id, relation, created_at) VALUES (?, ?, ?, ?)",
                        (a_id, b_id, relation, now),
                    )
            except sqlite3.IntegrityError as exc:
                raise InvalidInput("这两条记录之间已存在相同类型的关联") from exc
            link = {
                "id": int(cursor.lastrowid),
                "a_id": a_id,
                "b_id": b_id,
                "relation": relation,
                "created": now,
            }
            self._links[link["id"]] = link
            self._touch()
            return dict(link)

    def delete_link(self, link_id: int) -> None:
        with self._mu:
            self._require_unlocked()
            link_id = int(link_id)
            if link_id not in self._links:
                raise VaultError("关联不存在")
            with self._conn:
                self._conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
            self._links.pop(link_id, None)
            self._touch()

    # ------------------------------------------------------------------ #
    # 账号组（把多个账号打包成一行展示）
    # ------------------------------------------------------------------ #
    def _clean_member_ids(self, member_ids: Any) -> list[int]:
        if member_ids is None:
            return []
        if not isinstance(member_ids, (list, tuple, set)):
            raise InvalidInput("成员格式不正确")
        cleaned: list[int] = []
        for raw in member_ids:
            try:
                account_id = int(raw)
            except (TypeError, ValueError) as exc:
                raise InvalidInput("成员 id 不正确") from exc
            if account_id not in self._accounts:
                raise InvalidInput(f"账号 #{account_id} 不存在")
            if account_id not in cleaned:
                cleaned.append(account_id)
        return cleaned

    @staticmethod
    def _public_group(group: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": group["id"],
            "name": group["name"],
            "note": group["note"],
            "created": group["created"],
            "updated": group["updated"],
            "member_ids": list(group["member_ids"]),
        }

    def create_group(self, name: str, note: str = "", member_ids: Any = ()) -> dict[str, Any]:
        with self._mu:
            self._require_unlocked()
            cleaned_name = _clean_text(name, "group_name")
            if not cleaned_name:
                raise InvalidInput("账号组名称不能为空")
            cleaned_note = _clean_text(note, "group_note", strip=False).strip()
            members = self._clean_member_ids(member_ids)
            now = time.time()
            payload = self._encode_group(cleaned_name, cleaned_note)
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO groups (payload, created_at, updated_at) VALUES (?, ?, ?)",
                    (payload, now, now),
                )
                group_id = int(cursor.lastrowid)
                for account_id in members:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO group_members (group_id, account_id) VALUES (?, ?)",
                        (group_id, account_id),
                    )
            group = {
                "id": group_id,
                "name": cleaned_name,
                "note": cleaned_note,
                "created": now,
                "updated": now,
                "member_ids": members,
            }
            self._groups[group_id] = group
            self._touch()
            return self._public_group(group)

    def update_group(
        self,
        group_id: int,
        *,
        name: str | None = None,
        note: str | None = None,
        member_ids: Any = None,
    ) -> dict[str, Any]:
        with self._mu:
            self._require_unlocked()
            group_id = int(group_id)
            existing = self._groups.get(group_id)
            if existing is None:
                raise VaultError("账号组不存在")
            new_name = existing["name"] if name is None else _clean_text(name, "group_name")
            if not new_name:
                raise InvalidInput("账号组名称不能为空")
            new_note = (
                existing["note"] if note is None else _clean_text(note, "group_note", strip=False).strip()
            )
            members = (
                list(existing["member_ids"]) if member_ids is None else self._clean_member_ids(member_ids)
            )
            now = time.time()
            payload = self._encode_group(new_name, new_note)
            with self._conn:
                self._conn.execute(
                    "UPDATE groups SET payload = ?, updated_at = ? WHERE id = ?",
                    (payload, now, group_id),
                )
                self._conn.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
                for account_id in members:
                    self._conn.execute(
                        "INSERT INTO group_members (group_id, account_id) VALUES (?, ?)",
                        (group_id, account_id),
                    )
            group = {
                "id": group_id,
                "name": new_name,
                "note": new_note,
                "created": existing["created"],
                "updated": now,
                "member_ids": members,
            }
            self._groups[group_id] = group
            self._touch()
            return self._public_group(group)

    def delete_group(self, group_id: int) -> None:
        with self._mu:
            self._require_unlocked()
            group_id = int(group_id)
            if group_id not in self._groups:
                raise VaultError("账号组不存在")
            with self._conn:
                self._conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            self._groups.pop(group_id, None)
            self._touch()

    # ------------------------------------------------------------------ #
    # 主密码修改 / 导出 / 快照
    # ------------------------------------------------------------------ #
    def change_password(self, old: str, new: str) -> None:
        with self._mu:
            self._require_unlocked()
            assert self._key is not None
            self._validate_master_password(new)
            salt = _b64d(self._meta_get("salt") or "")
            iterations = int(self._meta_get("iterations") or crypto.DEFAULT_ITERATIONS)
            try:
                token = crypto.decrypt(
                    crypto.derive_key(old, salt, iterations),
                    _b64d(self._meta_get("verifier") or ""),
                    AAD_VERIFIER,
                )
            except crypto.CipherError:
                token = b""
            if token != _VERIFIER_TOKEN:
                raise BadPassword("原主密码错误")

            new_salt = crypto.random_bytes(SALT_SIZE)
            new_key = crypto.derive_key(new, new_salt, crypto.DEFAULT_ITERATIONS)

            # 内存里本来就是明文缓存：直接用新密钥重新加密全部记录，再一次性写入。
            reencrypted = [
                (self._encode(account, new_key), account_id)
                for account_id, account in self._accounts.items()
            ]
            group_payloads = [
                (self._encode_group(group["name"], group["note"], new_key), group_id)
                for group_id, group in self._groups.items()
            ]

            with self._conn:
                for payload, account_id in reencrypted:
                    self._conn.execute(
                        "UPDATE accounts SET payload = ? WHERE id = ?",
                        (payload, account_id),
                    )
                for payload, group_id in group_payloads:
                    self._conn.execute(
                        "UPDATE groups SET payload = ? WHERE id = ?",
                        (payload, group_id),
                    )
                self._meta_set("salt", _b64e(new_salt))
                self._meta_set("iterations", str(crypto.DEFAULT_ITERATIONS))
                self._meta_set(
                    "verifier", _b64e(crypto.encrypt(new_key, _VERIFIER_TOKEN, AAD_VERIFIER))
                )
            self._key = new_key
            self._touch()

    def snapshot(self) -> dict[str, Any]:
        """返回整个库的明文快照（仅内存中，不写盘）。"""
        with self._mu:
            self._require_unlocked()
            self._touch()
            accounts = sorted(
                (self._public(a) for a in self._accounts.values()),
                key=lambda a: (a["category"] == "", a["title"].lower(), a["id"]),
            )
            links = sorted(self._links.values(), key=lambda link: link["id"])
            groups = sorted(
                (self._public_group(g) for g in self._groups.values()),
                key=lambda g: (g["name"].lower(), g["id"]),
            )
            return {
                "accounts": accounts,
                "links": [dict(link) for link in links],
                "groups": groups,
            }

    def export_plain(self) -> dict[str, Any]:
        with self._mu:
            data = self.snapshot()
            return {
                "format": "password-vault-json",
                "version": 1,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "warning": "此文件包含明文密码，请妥善保管并在导入后删除。",
                "accounts": data["accounts"],
                "links": data["links"],
                "groups": data["groups"],
            }

    def backup(self, directory: str | os.PathLike[str], *, keep: int = 10) -> Path:
        """把当前加密库完整复制一份（仍是主密码加密的 .db 文件）。

        * 用 SQLite 的在线备份接口生成一致性快照，不会因写入中断而损坏；
        * 文件名形如 ``vault-20261028-114530.db``；
        * 自动轮转，只保留最近 ``keep`` 份，避免越积越多。
        """
        with self._mu:
            self._require_unlocked()
            target_dir = Path(directory)
            target_dir.mkdir(parents=True, exist_ok=True)

            stamp = time.strftime("vault-%Y%m%d-%H%M%S")
            target = target_dir / f"{stamp}.db"
            counter = 1
            while target.exists():
                target = target_dir / f"{stamp}-{counter}.db"
                counter += 1

            destination = sqlite3.connect(str(target))
            try:
                self._conn.backup(destination)
                destination.commit()
            finally:
                destination.close()

            try:
                existing = sorted(p for p in target_dir.glob("vault-*.db") if p.is_file())
                for old in existing[:-keep]:
                    old.unlink()
            except OSError:
                pass
            return target
