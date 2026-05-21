"""
Unit tests for app/core/cleanup.py.

We exercise:
  * _sweep_once         — deletes only rows older than the TTL.
  * inbox_cleanup_loop  — runs at least one iteration and exits cleanly
                          when stop_event is set.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import cleanup as cleanup_module
from app.models.models import Message, User


@pytest.fixture()
async def patched_factory(async_engine):
    """
    Point cleanup._sweep_once at the test engine for the duration of a test.
    cleanup imports async_session_factory at module load, so we have to patch
    the symbol it captured.
    """
    factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)
    with patch.object(cleanup_module, "async_session_factory", factory):
        yield factory


async def _seed(factory, *, old_count: int, fresh_count: int):
    """Insert one user and N old + N fresh messages."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cleanup_module.INBOX_TTL_DAYS)
    async with factory() as session:
        session.add(User(telegram_id=11, username="recipient"))
        await session.flush()
        for i in range(old_count):
            session.add(
                Message(
                    recipient_id=11,
                    sender_id=22,
                    encrypted_payload=f"old-{i}",
                    timestamp=cutoff - timedelta(hours=1),
                )
            )
        for i in range(fresh_count):
            session.add(
                Message(
                    recipient_id=11,
                    sender_id=22,
                    encrypted_payload=f"new-{i}",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        await session.commit()


class TestSweepOnce:
    @pytest.mark.asyncio
    async def test_deletes_only_expired_rows(self, patched_factory):
        await _seed(patched_factory, old_count=3, fresh_count=2)
        deleted = await cleanup_module._sweep_once()
        assert deleted == 3
        async with patched_factory() as session:
            remaining = (await session.execute(select(Message))).scalars().all()
            assert len(remaining) == 2
            assert all(m.encrypted_payload.startswith("new-") for m in remaining)

    @pytest.mark.asyncio
    async def test_nothing_to_delete_returns_zero(self, patched_factory):
        await _seed(patched_factory, old_count=0, fresh_count=4)
        deleted = await cleanup_module._sweep_once()
        assert deleted == 0


class TestInboxCleanupLoop:
    @pytest.mark.asyncio
    async def test_loop_sweeps_then_exits_on_stop(self, patched_factory):
        """One iteration runs, sweep is called, the loop honours stop_event."""
        await _seed(patched_factory, old_count=2, fresh_count=0)

        stop = asyncio.Event()
        # Tight interval so the loop reaches the wait before we set stop.
        with patch.object(cleanup_module, "SWEEP_INTERVAL_SECONDS", 0.01):
            task = asyncio.create_task(cleanup_module.inbox_cleanup_loop(stop))
            # Give the first sweep a moment to land, then stop the loop.
            await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, timeout=1.0)

        async with patched_factory() as session:
            remaining = (await session.execute(select(Message))).scalars().all()
            assert remaining == []

    @pytest.mark.asyncio
    async def test_loop_survives_sweep_failure(self, patched_factory):
        """If _sweep_once raises, the loop must log and keep going (until stop)."""
        stop = asyncio.Event()
        with patch.object(cleanup_module, "SWEEP_INTERVAL_SECONDS", 0.01):
            with patch.object(cleanup_module, "_sweep_once", side_effect=RuntimeError("boom")):
                task = asyncio.create_task(cleanup_module.inbox_cleanup_loop(stop))
                await asyncio.sleep(0.05)
                stop.set()
                await asyncio.wait_for(task, timeout=1.0)
        # We don't assert anything beyond "task exits cleanly" — surviving the
        # exception is the contract.
