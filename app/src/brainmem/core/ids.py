"""ID 生成：ULID 兼容字符串（26 位 Crockford Base32，前 10 位为毫秒时间戳，可按时间排序）。

自包含实现，避免第三方 ulid 包的 API 差异；输出与标准 ULID 同构。
"""
import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_id() -> str:
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bit 随机
    return _encode(ts, 10) + _encode(rand, 16)
