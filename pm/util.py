"""通用小工具：密码生成、强度评估、时间格式化。"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

# 去掉容易混淆的字符（l / I / O / 0 / 1），减少抄写错误
LOWER = "abcdefghijkmnopqrstuvwxyz"
UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
DIGITS = "23456789"
SYMBOLS = "!@#$%^&*()-_=+[]{}:,.?/~"


def generate_password(
    length: int = 20,
    *,
    lower: bool = True,
    upper: bool = True,
    digits: bool = True,
    symbols: bool = True,
) -> str:
    """用 ``secrets``（操作系统级 CSPRNG）生成随机密码。

    保证每种勾选的字符类型至少出现一次，其余字符从合并字符集中随机抽取。
    """
    length = max(4, min(int(length), 128))
    pools = [
        pool
        for pool, enabled in (
            (LOWER, lower),
            (UPPER, upper),
            (DIGITS, digits),
            (SYMBOLS, symbols),
        )
        if enabled
    ]
    if not pools:
        pools = [LOWER]

    chars = [secrets.choice(pool) for pool in pools]
    alphabet = "".join(pools)
    while len(chars) < length:
        chars.append(secrets.choice(alphabet))

    # Fisher–Yates 洗牌，让必选字符的位置也随机
    for index in range(len(chars) - 1, 0, -1):
        swap = secrets.randbelow(index + 1)
        chars[index], chars[swap] = chars[swap], chars[index]

    return "".join(chars[:length])


STRENGTH_LABELS = ("—", "很弱", "弱", "一般", "较强", "很强")
STRENGTH_COLORS = ("#7b8497", "#e5484d", "#e5484d", "#f0a020", "#129a5b", "#0e7a47")


def password_strength(password: str) -> tuple[int, str, str]:
    """返回 (0-5 的分数, 文字标签, 颜色)。"""
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if any(c.islower() for c in password) and any(c.isupper() for c in password):
        score += 1
    if any(c.isdigit() for c in password):
        score += 1
    if any(not c.isalnum() for c in password):
        score += 1
    score = min(score, 5)
    return score, STRENGTH_LABELS[score], STRENGTH_COLORS[score]


def fmt_time(timestamp: float | None) -> str:
    if not timestamp:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(timestamp)))


def looks_like_email(value: str) -> bool:
    """宽松判断：只要形如 ``local@domain`` 就当作邮箱地址（不追求 RFC 严格性）。"""
    text = (value or "").strip()
    if not text or " " in text:
        return False
    local, _, domain = text.partition("@")
    return bool(local) and bool(domain) and not domain.startswith(".") and not domain.endswith(".")


#: 常见邮箱服务商：域名 -> (名称, 登录网址)
EMAIL_PROVIDERS: dict[str, tuple[str, str]] = {
    # Gmail
    "gmail.com": ("Gmail", "https://mail.google.com"),
    "googlemail.com": ("Gmail", "https://mail.google.com"),
    # 腾讯
    "qq.com": ("QQ 邮箱", "https://mail.qq.com"),
    "foxmail.com": ("QQ 邮箱", "https://mail.qq.com"),
    "vip.qq.com": ("QQ 邮箱", "https://mail.qq.com"),
    # 网易
    "163.com": ("网易邮箱", "https://mail.163.com"),
    "vip.163.com": ("网易 VIP 邮箱", "https://vipmail.163.com"),
    "126.com": ("网易邮箱", "https://mail.126.com"),
    "yeah.net": ("网易 Yeah 邮箱", "https://mail.yeah.net"),
    # 国内其他
    "sina.com": ("新浪邮箱", "https://mail.sina.com.cn"),
    "sina.cn": ("新浪邮箱", "https://mail.sina.com.cn"),
    "sohu.com": ("搜狐邮箱", "https://mail.sohu.com"),
    "aliyun.com": ("阿里邮箱", "https://mail.aliyun.com"),
    "189.cn": ("天翼邮箱", "https://webmail.189.cn"),
    "139.com": ("中国移动邮箱", "https://mail.10086.cn"),
    "wo.cn": ("联通邮箱", "https://mail.wo.cn"),
    "263.net": ("263 邮箱", "https://mail.263.net"),
    # 微软
    "outlook.com": ("Outlook", "https://outlook.live.com/mail/"),
    "hotmail.com": ("Outlook", "https://outlook.live.com/mail/"),
    "live.com": ("Outlook", "https://outlook.live.com/mail/"),
    "live.cn": ("Outlook", "https://outlook.live.com/mail/"),
    "msn.com": ("Outlook", "https://outlook.live.com/mail/"),
    # 国外常见
    "yahoo.com": ("Yahoo 邮箱", "https://mail.yahoo.com"),
    "yahoo.co.jp": ("Yahoo 邮箱", "https://mail.yahoo.co.jp"),
    "icloud.com": ("iCloud 邮箱", "https://www.icloud.com/mail"),
    "me.com": ("iCloud 邮箱", "https://www.icloud.com/mail"),
    "mac.com": ("iCloud 邮箱", "https://www.icloud.com/mail"),
    "protonmail.com": ("Proton Mail", "https://mail.proton.me"),
    "proton.me": ("Proton Mail", "https://mail.proton.me"),
    "pm.me": ("Proton Mail", "https://mail.proton.me"),
    "tutanota.com": ("Tutanota", "https://app.tuta.com"),
    "tuta.io": ("Tutanota", "https://app.tuta.com"),
    "zoho.com": ("Zoho Mail", "https://mail.zoho.com"),
    "yandex.com": ("Yandex 邮箱", "https://mail.yandex.com"),
    "yandex.ru": ("Yandex 邮箱", "https://mail.yandex.ru"),
    "mail.ru": ("Mail.ru", "https://e.mail.ru/inbox/"),
    "aol.com": ("AOL 邮箱", "https://mail.aol.com"),
    "gmx.com": ("GMX", "https://www.gmx.com"),
    "gmx.net": ("GMX", "https://www.gmx.net"),
    "fastmail.com": ("Fastmail", "https://app.fastmail.com"),
    "hey.com": ("HEY", "https://app.hey.com"),
}


def lookup_email_provider(email: str) -> tuple[str, str] | None:
    """根据邮箱后缀返回 ``(服务商名称, 登录网址)``；识别不到返回 ``None``。

    会先精确匹配域名，再尝试去掉子域名匹配（例如 ``mail.qq.com`` → ``qq.com``）。
    """
    text = (email or "").strip().lower()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip(" .")
    if not domain:
        return None
    if domain in EMAIL_PROVIDERS:
        return EMAIL_PROVIDERS[domain]
    parts = domain.split(".")
    for index in range(1, len(parts) - 1):
        candidate = ".".join(parts[index:])
        if candidate in EMAIL_PROVIDERS:
            return EMAIL_PROVIDERS[candidate]
    return None


def normalize_url(url: str) -> str:
    """用于比较两个网址是否等价（忽略大小写、首尾空白与结尾斜杠）。"""
    return (url or "").strip().lower().rstrip("/")


def default_backup_dir(db_path: str | Path) -> Path:
    """加密备份的默认目录。

    故意放在**项目目录之外**（Windows 为 ``%LOCALAPPDATA%\\PasswordVault\\backups``），
    这样即使把整个 ``data/`` 目录误删，备份仍然存在，可以在启动时一键恢复。
    """
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "PasswordVault" / "backups"
    return Path(db_path).parent / "backups"


def avatar_letter(title: str) -> str:
    text = (title or "").strip()
    return text[0].upper() if text else "?"
