"""纯 Python 标准库实现的加密原语。

本模块只依赖 ``hashlib`` / ``hmac`` / ``os`` / ``struct``，无第三方包：

* 口令派生：PBKDF2-HMAC-SHA256（``hashlib`` 为 C 实现，速度足够）
* 认证加密：ChaCha20-Poly1305 AEAD（RFC 8439，本文件内实现）

ChaCha20-Poly1305 是 TLS 1.3 的强制套件之一，用在这里做"静态数据加密"很合适：
只需要一个 32 字节密钥、12 字节随机 nonce，就能得到"密文 + 16 字节认证标签"，
任何篡改都会在解密时被拒绝。

实现严格按 RFC 8439，并由 ``tools/selftest.py`` 中的官方测试向量校验。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

__all__ = [
    "CipherError",
    "KEY_SIZE",
    "NONCE_SIZE",
    "TAG_SIZE",
    "DEFAULT_ITERATIONS",
    "derive_key",
    "encrypt",
    "decrypt",
    "random_bytes",
]

M32 = 0xFFFFFFFF
_SIGMA = b"expand 32-byte k"

KEY_SIZE = 32
NONCE_SIZE = 12
TAG_SIZE = 16
#: 主密码派生迭代次数。仅一次解锁时计算，600k 次在普通机器上约 0.2~0.5 秒。
DEFAULT_ITERATIONS = 600_000


class CipherError(Exception):
    """密文被篡改、密钥错误或数据损坏。"""


# --------------------------------------------------------------------------- #
# ChaCha20
# --------------------------------------------------------------------------- #
def _rotl(word: int, shift: int) -> int:
    return ((word << shift) & M32) | (word >> (32 - shift))


def _quarter_round(x: list[int], a: int, b: int, c: int, d: int) -> None:
    x[a] = (x[a] + x[b]) & M32
    x[d] = _rotl(x[d] ^ x[a], 16)
    x[c] = (x[c] + x[d]) & M32
    x[b] = _rotl(x[b] ^ x[c], 12)
    x[a] = (x[a] + x[b]) & M32
    x[d] = _rotl(x[d] ^ x[a], 8)
    x[c] = (x[c] + x[d]) & M32
    x[b] = _rotl(x[b] ^ x[c], 7)


def _block(key: bytes, counter: int, nonce: bytes) -> bytes:
    """生成一个 64 字节的 ChaCha20 密钥流块。"""
    state = (
        list(struct.unpack("<4I", _SIGMA))
        + list(struct.unpack("<8I", key))
        + [counter & M32]
        + list(struct.unpack("<3I", nonce))
    )
    x = state[:]
    for _ in range(10):  # 20 轮 = 10 次双轮
        _quarter_round(x, 0, 4, 8, 12)
        _quarter_round(x, 1, 5, 9, 13)
        _quarter_round(x, 2, 6, 10, 14)
        _quarter_round(x, 3, 7, 11, 15)
        _quarter_round(x, 0, 5, 10, 15)
        _quarter_round(x, 1, 6, 11, 12)
        _quarter_round(x, 2, 7, 8, 13)
        _quarter_round(x, 3, 4, 9, 14)
    return struct.pack("<16I", *[(x[i] + state[i]) & M32 for i in range(16)])


def _stream_xor(key: bytes, nonce: bytes, counter: int, data: bytes) -> bytes:
    if len(key) != KEY_SIZE:
        raise ValueError("ChaCha20 需要 32 字节密钥")
    if len(nonce) != NONCE_SIZE:
        raise ValueError("ChaCha20 需要 12 字节 nonce")
    out = bytearray(len(data))
    for offset in range(0, len(data), 64):
        chunk = data[offset : offset + 64]
        keystream = _block(key, counter, nonce)[: len(chunk)]
        mixed = int.from_bytes(chunk, "little") ^ int.from_bytes(keystream, "little")
        out[offset : offset + len(chunk)] = mixed.to_bytes(len(chunk), "little")
        counter = (counter + 1) & M32
    return bytes(out)


# --------------------------------------------------------------------------- #
# Poly1305
# --------------------------------------------------------------------------- #
def _poly1305(key: bytes, message: bytes) -> bytes:
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:32], "little")
    prime = (1 << 130) - 5
    acc = 0
    for offset in range(0, len(message), 16):
        chunk = message[offset : offset + 16]
        number = int.from_bytes(chunk, "little") + (1 << (8 * len(chunk)))
        acc = ((acc + number) * r) % prime
    acc = (acc + s) & ((1 << 128) - 1)
    return acc.to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    return b"\x00" * ((16 - len(data) % 16) % 16)


def _mac(key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    """RFC 8439 §2.8 中 Poly1305 的 MAC 输入格式。"""
    one_time_key = _block(key, 0, nonce)[:32]
    mac_data = (
        aad
        + _pad16(aad)
        + ciphertext
        + _pad16(ciphertext)
        + struct.pack("<Q", len(aad))
        + struct.pack("<Q", len(ciphertext))
    )
    return _poly1305(one_time_key, mac_data)


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #
def random_bytes(size: int) -> bytes:
    """密码学安全随机数。"""
    return os.urandom(size)


def derive_key(password: str, salt: bytes, iterations: int = DEFAULT_ITERATIONS) -> bytes:
    """由主密码派生出 32 字节数据密钥。"""
    if not isinstance(password, str) or not password:
        raise ValueError("主密码不能为空")
    if len(salt) < 16:
        raise ValueError("salt 长度不足")
    if not 10_000 <= iterations <= 10_000_000:
        raise ValueError("迭代次数超出合理范围")
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=KEY_SIZE
    )


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """AEAD 加密，返回 ``nonce || ciphertext || tag``。"""
    if len(key) != KEY_SIZE:
        raise ValueError("需要 32 字节密钥")
    nonce = random_bytes(NONCE_SIZE)
    ciphertext = _stream_xor(key, nonce, 1, plaintext)
    tag = _mac(key, nonce, aad, ciphertext)
    return nonce + ciphertext + tag


def decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    """AEAD 解密，认证失败时抛 :class:`CipherError`。"""
    if len(key) != KEY_SIZE:
        raise ValueError("需要 32 字节密钥")
    if not isinstance(blob, (bytes, bytearray)):
        raise CipherError("密文格式错误")
    blob = bytes(blob)
    if len(blob) < NONCE_SIZE + TAG_SIZE:
        raise CipherError("密文长度异常")
    nonce = blob[:NONCE_SIZE]
    tag = blob[-TAG_SIZE:]
    ciphertext = blob[NONCE_SIZE:-TAG_SIZE]
    expected = _mac(key, nonce, aad, ciphertext)
    if not hmac.compare_digest(expected, tag):
        raise CipherError("认证失败：密钥错误或数据被篡改")
    return _stream_xor(key, nonce, 1, ciphertext)
