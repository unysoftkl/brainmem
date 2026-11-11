"""Hypothesis 属性测试：复算一致、事件自洽、强化/衰减单调（UC-15/16/17）。"""
import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from brainmem.core.decay import bp, decay_bp
from brainmem.core.enums import EventType
from brainmem.core.models import WeightEvent
from brainmem.core.params import DEFAULT_PARAMS as P
from brainmem.core.weights import reinforce
from brainmem.engine.events import replay

SETTINGS = settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])


def _mk_chain(deltas: list[int]) -> list[WeightEvent]:
    events = []
    cur = 0
    for i, d in enumerate(deltas):
        after = cur + d
        events.append(
            WeightEvent(
                seq=i + 1, entity_kind="NODE", entity_id="x", event_type=EventType.DECAY,
                delta_bp=d, before_bp=cur, after_bp=after, reason="t", actor="sys",
                at_day=0.0, at_real=0,
            )
        )
        cur = after
    return events


@SETTINGS
@given(st.lists(st.integers(min_value=-5000, max_value=5000), min_size=1, max_size=60))
def test_replay_equals_last_after(deltas):
    events = _mk_chain(deltas)
    assert replay(events) == events[-1].after_bp


@SETTINGS
@given(st.lists(st.integers(min_value=-5000, max_value=5000), min_size=1, max_size=40))
def test_replay_order_independent(deltas):
    events = _mk_chain(deltas)
    shuffled = events[:]
    random.shuffle(shuffled)
    assert replay(shuffled) == replay(events)


@SETTINGS
@given(
    st.integers(min_value=0, max_value=200000),
    st.integers(min_value=0, max_value=24),
    st.floats(min_value=0.0, max_value=1000.0),
)
def test_reinforce_monotonic(wb, s, dt):
    new, s2, peak, ds = reinforce(wb, s, max(wb, 1), dt, P)
    assert new >= wb
    assert new <= bp(P.W_MAX)
    assert s2 >= s and s2 <= 24


@SETTINGS
@given(
    st.integers(min_value=1, max_value=200000),
    st.integers(min_value=0, max_value=24),
    st.floats(min_value=0.0, max_value=2000.0),
    st.floats(min_value=0.0, max_value=2000.0),
)
def test_decay_monotonic_in_time(wb, s, d1, d2):
    lo, hi = min(d1, d2), max(d1, d2)
    assert decay_bp(wb, s, hi, P) <= decay_bp(wb, s, lo, P)
