"""可插拔嵌入提供者。

默认 HashEmbedder：字符 + 二元组 + 三元组哈希到固定维度并 L2 归一，完全离线、
确定性（用 hashlib 而非内置 hash，避免进程盐化）、对中文友好。
生产可换成 sentence-transformers(bge-m3) 或云端 embedding —— 只要实现 encode()。
"""
from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    dim: int

    def encode(self, text: str) -> list[float]: ...


def _stable_hash(token: str, dim: int) -> tuple[int, int]:
    h = hashlib.md5(token.encode("utf-8")).digest()
    idx = int.from_bytes(h[:4], "big") % dim
    sign = 1 if (h[4] & 1) else -1
    return idx, sign


class HashEmbedder:
    """字符 n-gram 哈希嵌入（离线、确定性）。"""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        t = text.strip()
        toks = list(t)  # 单字
        toks += [t[i:i + 2] for i in range(len(t) - 1)]  # 二元组
        toks += [t[i:i + 3] for i in range(len(t) - 2)]  # 三元组
        return toks or [""]

    def encode(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in self._tokens(text):
            idx, sign = _stable_hash(tok, self.dim)
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()


class NullEmbedder:
    """无嵌入兜底：全部零向量（退化为纯 FTS/字面）。"""
    dim = 1

    def encode(self, text: str) -> list[float]:
        return [0.0]
