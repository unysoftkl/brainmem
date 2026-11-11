"""pytest 共享夹具。"""
import pytest

from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(1000.0)


@pytest.fixture
def mem(clock: FakeClock):
    m = Memory.in_memory(clock)
    yield m
    m.close()
