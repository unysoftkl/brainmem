"""实体 / 压缩器 / 冷存（阶段3 单元）。"""
from brainmem.services.blobstore import InMemoryBlobStore
from brainmem.services.compressor import FID_CONDENSED, FID_VESTIGE, condense, vestige
from brainmem.services.entities import entity_retention, extract_entities


def test_extract_entities_keeps_numbers_and_names():
    ents = extract_entities("张三在北京市买了3本书，2024年5月")
    joined = "".join(ents)
    assert "3" in joined
    assert any(x in joined for x in ["2024", "北京市", "张三"])


def test_entity_retention():
    orig = "张三在北京买了3本书"
    kept = "张三 北京 3"
    assert entity_retention(orig, kept) >= 0.5


def test_compressor_fidelity():
    g, f = condense("张三在北京市买了3本书")
    assert f == FID_CONDENSED and g
    g2, f2 = vestige("张三在北京市买了3本书")
    assert f2 == FID_VESTIGE


def test_blobstore_roundtrip():
    bs = InMemoryBlobStore()
    ref = bs.put("原文内容".encode("utf-8"))
    assert bs.get(ref).decode("utf-8") == "原文内容"
