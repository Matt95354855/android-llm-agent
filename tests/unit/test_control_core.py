import asyncio

import pytest

from control.locks import DeviceLocks, LeaseLost
from control.models import Controller, InvalidTransition, MissionStatus, check_transition


def test_terminal_states_cannot_restart():
    check_transition(MissionStatus.queued, MissionStatus.running)
    with pytest.raises(InvalidTransition):
        check_transition(MissionStatus.succeeded, MissionStatus.running)
    with pytest.raises(InvalidTransition):
        check_transition(MissionStatus.cancelled, MissionStatus.queued)


async def test_lock_is_exclusive_and_old_generation_is_rejected():
    locks = DeviceLocks(ttl_s=0.2)
    a = locks.try_acquire("tel-1", "agent:run1", Controller.agent)
    assert a and locks.try_acquire("tel-1", "user:x", Controller.user) is None
    await asyncio.sleep(0.25)  # bail expiré
    b = locks.try_acquire("tel-1", "user:x", Controller.user)
    assert b and b.generation == a.generation + 1
    with pytest.raises(LeaseLost):
        locks.validate(a)  # l'ancien worker ne peut plus injecter
    locks.validate(b)


async def test_acquire_waits_for_release():
    locks = DeviceLocks()
    a = locks.try_acquire("tel-2", "agent:1", Controller.agent)
    waiter = asyncio.create_task(locks.acquire("tel-2", "user:1", Controller.user, timeout=2))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await locks.release(a)
    b = await waiter
    assert b.owner == "user:1"
