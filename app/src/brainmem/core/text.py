"""文本规范化、字符计数、指纹（规范第 2.1 / 7 节）。"""
import hashlib
import unicodedata

# 繁简统一：阶段1 不引入 opencc 依赖，先做最小常见字映射 + 全角半角统一；
# 完整繁简转换在阶段 3 的 encoder 中补齐（不影响内核语义）。
_TRAD_TO_SIMP = {
    "學": "学", "數": "数", "記": "记", "憶": "忆", "數": "数",
    "體": "体", "庫": "库", "網": "网", "題": "题", "對": "对",
    "於": "于", "麼": "么", "這": "这", "個": "个", "們": "们",
}


def normalize(text: str) -> str:
    """去空白、全半角统一（NFKC）、繁简统一（最小集）。"""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if not ch.isspace())
    t = "".join(_TRAD_TO_SIMP.get(ch, ch) for ch in t)
    return t


def char_len(text: str) -> int:
    """Unicode 字符数（规范选 B：任何字符计 1）。"""
    return len(text)


def fingerprint(label_norm: str, source_kind: str) -> str:
    """SHA-256(label_norm + '\\x1f' + source_kind)。"""
    payload = f"{label_norm}\x1f{source_kind}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def make_gist(text: str, limit: int = 20) -> str:
    """阶段1 降级 gist：截断到 limit 字符（LLM 摘要在阶段3）。"""
    return text if len(text) <= limit else text[:limit]


def strip_edge_punct(text: str) -> str:
    """去掉首尾的标点/符号/分隔符（保留中间内容）。"""
    import unicodedata

    def junk(ch: str) -> bool:
        return unicodedata.category(ch)[0] in ("P", "S", "Z")

    t = text
    while t and junk(t[0]):
        t = t[1:]
    while t and junk(t[-1]):
        t = t[:-1]
    return t


def has_meaningful_char(text: str) -> bool:
    """是否至少含一个"实义"字符（字母/汉字/数字），而非纯标点/符号/空白。"""
    import unicodedata

    return any(unicodedata.category(ch)[0] in ("L", "N") for ch in text)
