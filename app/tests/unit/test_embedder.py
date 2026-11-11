"""嵌入与相似度。"""
import math

from brainmem.services.embedder import HashEmbedder, NullEmbedder
from brainmem.services.similarity import cosine, edit_ratio, jaccard, similarity


def test_embedder_deterministic_and_normalized():
    e = HashEmbedder(dim=256)
    v1 = e.encode("数学")
    v2 = e.encode("数学")
    assert v1 == v2  # 确定性
    assert len(v1) == 256
    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-5  # L2 归一


def test_cosine_identity_and_unrelated():
    e = HashEmbedder(128)
    a = e.encode("数学")
    b = e.encode("数学")
    c = e.encode("苹果香蕉")
    assert abs(cosine(a, b) - 1.0) < 1e-5
    assert cosine(a, c) < cosine(a, b)


def test_similarity_identical_is_one():
    e = HashEmbedder(128)
    v = e.encode("数学")
    assert abs(similarity("数学", "数学", v, v) - 1.0) < 1e-6


def test_edit_and_jaccard():
    assert edit_ratio("数学", "数学") == 1.0
    assert jaccard("数学", "数学") == 1.0
    assert jaccard("数学", "语文") == 0.0


def test_null_embedder():
    n = NullEmbedder()
    assert n.encode("x") == [0.0]
