"""删除与审计（UC-18 ~ UC-19）。"""
import pytest

from brainmem.core.errors import NotFoundError


def test_uc18_hard_delete_with_audit(mem):
    r = mem.write("数学题")
    nid = r["id"]
    res = mem.forget(nid, "hard")
    assert res["deleted"] is True
    with pytest.raises(NotFoundError):
        mem.get(nid)
    # 审计事件仍在，且不含内容字段（WeightEvent 本身无 label/gist）
    evs = mem.storage.iter_events(nid)
    deletes = [e for e in evs if e.event_type.value == "DELETE"]
    assert deletes, "应有 DELETE 审计事件"
    assert all(e.reason in ("user_deleted", "weight_zero") for e in deletes)


def test_uc19_get_after_delete_raises(mem):
    r = mem.write("一二三")
    mem.forget(r["id"], "hard")
    with pytest.raises(NotFoundError):
        mem.get(r["id"])
