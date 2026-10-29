"""加密原语自检：使用 RFC 8439 官方测试向量。

用法::

    python tools/selftest.py crypto
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm import crypto  # noqa: E402


def h(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", "").replace("\n", ""))


def check(name: str, got: bytes, want: bytes) -> None:
    if got != want:
        raise SystemExit(
            f"[FAIL] {name}\n  got : {got.hex()}\n  want: {want.hex()}"
        )
    print(f"  [ok] {name}")


def test_chacha20_block() -> None:
    key = h("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    nonce = h("000000090000004a00000000")
    want = h(
        "10f1e7e4d13b5915500fdd1fa32071c4c7d1f4c733c068030422aa9ac3d46c4e"
        "d2826446079faa0914c2d705d98b02a2b5129cd1de164eb9cbd083e8a2503c4e"
    )
    check("RFC 8439 §2.3.2 ChaCha20 block", crypto._block(key, 1, nonce), want)


def test_chacha20_stream() -> None:
    key = h("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    nonce = h("000000000000004a00000000")
    plaintext = (
        b"Ladies and Gentlemen of the class of '99: If I could offer you "
        b"only one tip for the future, sunscreen would be it."
    )
    want = h(
        "6e2e359a2568f98041ba0728dd0d6981e97e7aec1d4360c20a27afccfd9fae0b"
        "f91b65c5524733ab8f593dabcd62b3571639d624e65152ab8f530c359f0861d8"
        "07ca0dbf500d6a6156a38e088a22b65e52bc514d16ccf806818ce91ab7793736"
        "5af90bbf74a35be6b40b8eedf2785e42874d"
    )
    check(
        "RFC 8439 §2.4.2 ChaCha20 加密",
        crypto._stream_xor(key, nonce, 1, plaintext),
        want,
    )


def test_poly1305() -> None:
    key = h("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
    want = h("a8061dc1305136c6c22b8baf0c0127a9")
    check(
        "RFC 8439 §2.5.2 Poly1305 一次性认证码",
        crypto._poly1305(key, b"Cryptographic Forum Research Group"),
        want,
    )


def test_aead_vector() -> None:
    key = h("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
    nonce = h("070000004041424344454647")
    aad = h("50515253c0c1c2c3c4c5c6c7")
    plaintext = (
        b"Ladies and Gentlemen of the class of '99: If I could offer you "
        b"only one tip for the future, sunscreen would be it."
    )
    want_ct = h(
        "d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d6"
        "3dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b36"
        "92ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc"
        "3ff4def08e4b7a9de576d26586cec64b6116"
    )
    want_tag = h("1ae10b594f09e26a7e902ecbd0600691")

    ciphertext = crypto._stream_xor(key, nonce, 1, plaintext)
    check("RFC 8439 §2.8.2 AEAD 密文", ciphertext, want_ct)
    check("RFC 8439 §2.8.2 Poly1305 标签", crypto._mac(key, nonce, aad, ciphertext), want_tag)


def test_roundtrip_and_tamper() -> None:
    key = crypto.random_bytes(crypto.KEY_SIZE)
    payload = (
        "中文、emoji 🔐 和长文本 " * 40
    ).encode("utf-8") + bytes(range(256))

    blob = crypto.encrypt(key, payload, aad=b"account")
    check("加解密往返（>1KB 多分块）", crypto.decrypt(key, blob, aad=b"account"), payload)

    # 篡改任意一个比特都必须被发现
    for pos in (0, crypto.NONCE_SIZE, len(blob) // 2, len(blob) - 1):
        broken = bytearray(blob)
        broken[pos] ^= 0x01
        try:
            crypto.decrypt(key, bytes(broken), aad=b"account")
        except crypto.CipherError:
            continue
        raise SystemExit(f"[FAIL] 篡改字节 {pos} 未被检测到")

    # 错误的 AAD 与错误的密钥也必须失败
    for kwargs in (
        {"key": key, "aad": b"other"},
        {"key": crypto.random_bytes(crypto.KEY_SIZE), "aad": b"account"},
    ):
        try:
            crypto.decrypt(kwargs["key"], blob, aad=kwargs["aad"])
        except crypto.CipherError:
            continue
        raise SystemExit("[FAIL] 错误上下文竟然解密成功")
    print("  [ok] 篡改/错误密钥/AAD 均被拒绝")

    # 每次加密的随机 nonce 不同
    if crypto.encrypt(key, b"x")[:crypto.NONCE_SIZE] == crypto.encrypt(key, b"x")[:crypto.NONCE_SIZE]:
        raise SystemExit("[FAIL] nonce 未随机化")
    print("  [ok] nonce 随机化")


def test_kdf_and_speed() -> None:
    salt = crypto.random_bytes(16)
    started = time.perf_counter()
    key = crypto.derive_key("正确的马电池订书钉", salt)
    cost = time.perf_counter() - started
    check("PBKDF2 派生稳定性", crypto.derive_key("正确的马电池订书钉", salt), key)
    if crypto.derive_key("另一个口令", salt) == key:
        raise SystemExit("[FAIL] 不同口令派生出相同密钥")
    print(f"  [ok] PBKDF2 600k 次耗时 {cost * 1000:.0f} ms")

    # 吞吐量参考，确认加解密对个人密码库足够快
    bulk = crypto.random_bytes(256 * 1024)
    started = time.perf_counter()
    crypto.decrypt(key, crypto.encrypt(key, bulk))
    speed = 256 / 1024 / (time.perf_counter() - started)
    print(f"  [ok] 256 KiB 加解密往返 {speed:.1f} MiB/s（一次解锁全库解密即可缓存）")
    if speed < 0.1:
        raise SystemExit("[FAIL] 加密速度异常，库实现可能有问题")


def main() -> int:
    print("== ChaCha20-Poly1305 / PBKDF2 自检 ==")
    test_chacha20_block()
    test_chacha20_stream()
    test_poly1305()
    test_aead_vector()
    test_roundtrip_and_tamper()
    test_kdf_and_speed()
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
