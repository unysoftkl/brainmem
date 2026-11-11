"""相似度合成（设计书 5.3）：s = 0.5*cos + 0.3*edit_ratio + 0.2*jaccard。"""
from __future__ import annotations

import difflib

import numpy as np


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def edit_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def jaccard(a: str, b: str) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similarity(a: str, b: str, emb_a: list[float], emb_b: list[float]) -> float:
    return 0.5 * cosine(emb_a, emb_b) + 0.3 * edit_ratio(a, b) + 0.2 * jaccard(a, b)
