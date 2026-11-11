"""写入与初始权重（UC-01 ~ UC-05）。"""
import pytest

from brainmem.core.errors import TooLongError


def test_uc01_short_atom(mem):
    r = mem.write("数学题")  # 3 字
    assert r["created"] is True
    assert r["weight"] == "6.00"
    assert r["state"] == "NORMAL"


def test_uc02_initial_weight_ladder(mem):
    words = ["一", "二二", "三三三", "四四四四", "五五五五五",
             "六六六六六六", "七七七七七七七", "八八八八八八八八",
             "九九九九九九九九九", "十十十十十十十十十十"]
    exp_w = ["8.00", "7.00", "6.00", "5.50", "5.00", "4.50", "4.00", "3.00", "2.00", "1.00"]
    exp_s = ["FULL", "FULL", "NORMAL", "NORMAL", "NORMAL", "NORMAL", "NORMAL",
             "CONDENSED", "CONDENSED", "VESTIGE"]
    for w, ew, es in zip(words, exp_w, exp_s):
        r = mem.write(w)
        assert r["weight"] == ew, f"{w}"
        assert r["state"] == es, f"{w}"


def test_uc03_eight_char_is_blurry(mem):
    r = mem.write("一二三四五六七八")
    assert r["weight"] == "3.00"
    assert r["state"] == "CONDENSED"
    got = mem.get(r["id"])
    assert got["fidelity"] == 85


def test_uc04_empty_rejected(mem):
    with pytest.raises(TooLongError):
        mem.write("")


def test_uc04b_long_text_now_allowed(mem):
    # 新策略：字数由 AI 决定，库按字数给权重；>10 字不再拒绝。
    r = mem.write("这是一个超过十个字符的完整句子内容")
    assert r["created"] is True
    assert r["weight"] == "0.86" or float(r["weight"]) < 1.00  # 15字，单调下降


def test_uc04c_write_note_title_plus_verbatim(mem):
    # 超长内容用 write_note：短标题入库、原文进冷存
    r = mem.write_note("长句子", "这是一个超过十个字符的完整句子内容，用于验证原文冷存。")
    assert r["created"] is True
    got = mem.get(r["id"], include_verbatim=True)
    assert got["label"] == "长句子"
    assert "完整句子内容" in (got.get("verbatim") or got.get("gist") or "")
    # 标题超 MAX_LABEL_CHARS 才拒绝
    from brainmem.core.tables import MAX_LABEL_CHARS
    with pytest.raises(TooLongError):
        mem.write_note("字" * (MAX_LABEL_CHARS + 1), "内容")


def test_uc05_idempotent_within_window(mem, clock):
    r1 = mem.write("数学")
    clock.advance_minutes(1)
    r2 = mem.write("数学")
    assert r2["created"] is False
    assert r2["deduped"] is True
    assert r2["id"] == r1["id"]
    assert r2["weight"] == r1["weight"]  # 不强化
