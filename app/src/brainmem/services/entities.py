"""实体抽取（压缩时保留"再认锚点"：人名/地名/机构/数字/时间/专名）。

用 jieba 词性 + 正则兜底；jieba 不可用时降级为正则。
"""
from __future__ import annotations

import re

try:
    import jieba.posseg as _pseg
    _HAS_JIEBA = True
except Exception:  # pragma: no cover
    _HAS_JIEBA = False

# 保留的词性：nr 人名 / ns 地名 / nt 机构 / nz 专名 / m 数词 / eng 英文 / j 简称 / l 习语
_KEEP_FLAGS = {"nr", "ns", "nt", "nz", "m", "eng", "j", "l"}
_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?|[A-Za-z][A-Za-z0-9]+")


def extract_entities(text: str) -> list[str]:
    ents: list[str] = []
    if _HAS_JIEBA:
        try:
            for w, flag in _pseg.cut(text):
                w = w.strip()
                if w and flag in _KEEP_FLAGS:
                    ents.append(w)
        except Exception:
            pass
    for m in _NUM_RE.findall(text):
        ents.append(m)
    seen: set[str] = set()
    out: list[str] = []
    for e in ents:
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


def entity_retention(original: str, compressed: str) -> float:
    """压缩后仍保留的原实体比例（用于验收指标）。"""
    ents = extract_entities(original)
    if not ents:
        return 1.0
    kept = sum(1 for e in ents if e in compressed)
    return kept / len(ents)
