"""压缩器（设计书 6.1/6.2）：三级压缩的内容变换（纯函数）。

- CONDENSED：gist = 关键实体 + 主旨片段，保真度 60–85（默认 70），原文仍在冷存。
- VESTIGE：gist = 实体/摘要一句话，保真度 20–40（默认 30），仅留摘要+指纹+来源。
压缩"不是删除"，原文始终在 BlobStore 可回读。
"""
from __future__ import annotations

from brainmem.services.entities import extract_entities

FID_CONDENSED = 70
FID_VESTIGE = 30


def condense_gist(text: str, entities: list[str] | None = None) -> str:
    ents = entities if entities is not None else extract_entities(text)
    if ents:
        # 关键实体全部保留（再认锚点），再拼主旨片段；不截断实体
        return "、".join(ents) + "｜" + text[:12]
    return text[:20]


def vestige_summary(text: str, entities: list[str] | None = None) -> str:
    ents = entities if entities is not None else extract_entities(text)
    if ents:
        return "、".join(ents)  # 残迹仅留实体锚点
    return text[:12]


def condense(text: str) -> tuple[str, int]:
    """返回 (gist, fidelity)。"""
    return condense_gist(text), FID_CONDENSED


def vestige(text: str) -> tuple[str, int]:
    return vestige_summary(text), FID_VESTIGE
