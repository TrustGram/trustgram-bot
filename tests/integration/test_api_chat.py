"""
Integration tests for the chat / messaging API (app/api/v1/chat.py).

Covers
------
POST /api/v1/chat/send
  - Delivers an encrypted blob → 201.
  - Message stored with correct sender_id.

GET /api/v1/chat/inbox
  - Returns only the current user's messages.
  - Messages are ordered by timestamp ascending.
  - Returns empty list when inbox is empty.

DELETE /api/v1/chat/message/{id}
  - Deletes a message belonging to the current user → 200.
  - Returns 404 for a non-existent message ID.
  - Returns 404 when message belongs to a different user.
"""

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
async def _register_recipients(db_session):
    """POST /chat/send now 404s on an unregistered recipient (FK + anti-spam),
    so pre-create the ids these tests deliver to: 12345678 is the mock user,
    the rest are the 'other' recipients used across the module."""
    from app.models.models import User

    for tid in (12345678, 77777777, 99999, 11111111):
        db_session.add(User(telegram_id=tid))
    await db_session.flush()


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_returns_201(self, client: AsyncClient):
        payload = {"recipient_id": 99999, "encrypted_payload": "cipher_blob"}
        resp = await client.post("/api/v1/chat/send", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["detail"] == "Message delivered to inbox"

    @pytest.mark.asyncio
    async def test_send_to_unregistered_recipient_returns_404(self, client: AsyncClient):
        """Delivering to an id with no registered user is rejected — otherwise it
        would FK-500 on Postgres / store an undeliverable orphan row on SQLite."""
        # 55555 is deliberately NOT in the _register_recipients fixture.
        resp = await client.post(
            "/api/v1/chat/send",
            json={"recipient_id": 55555, "encrypted_payload": "blob"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Recipient not found"

    @pytest.mark.asyncio
    async def test_notification_throttled_per_recipient(self, client: AsyncClient):
        """Rapid follow-up messages to the same recipient must not spam Telegram."""
        from app.api.v1 import chat as chat_mod
        from app.bot import bot as bot_mod

        chat_mod._last_notified.clear()
        bot_mod.bot.send_message.reset_mock()

        for i in range(5):
            await client.post(
                "/api/v1/chat/send",
                json={"recipient_id": 99999, "encrypted_payload": f"blob_{i}"},
            )
        # Only the first send should have pinged Telegram; the next four are
        # within the cooldown window.
        assert bot_mod.bot.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_send_stores_sender_id(self, client: AsyncClient):
        """
        Send a message to ourselves (recipient_id == mock user's id) and verify
        the stored sender_id equals the authenticated user.
        """
        payload = {"recipient_id": 12345678, "encrypted_payload": "self_msg"}
        await client.post("/api/v1/chat/send", json=payload)

        inbox = await client.get("/api/v1/chat/inbox")
        messages = inbox.json()["messages"]
        self_msg = next(m for m in messages if m["encrypted_payload"] == "self_msg")
        assert self_msg["sender_id"] == 12345678


class TestGetInbox:
    @pytest.mark.asyncio
    async def test_empty_inbox(self, client: AsyncClient):
        resp = await client.get("/api/v1/chat/inbox")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    @pytest.mark.asyncio
    async def test_first_fetch_stamps_timestamp(self, client: AsyncClient, db_session):
        """GET /inbox flips first_fetched_at from NULL → now(), idempotent on retry."""
        from datetime import datetime, timezone

        from sqlalchemy import select

        from app.models.models import Message

        await client.post(
            "/api/v1/chat/send",
            json={"recipient_id": 12345678, "encrypted_payload": "stamp_test"},
        )

        before = (await db_session.execute(select(Message))).scalars().first()
        assert before.first_fetched_at is None

        # First fetch — stamp gets set.
        await client.get("/api/v1/chat/inbox")
        await db_session.refresh(before)
        first_stamp = before.first_fetched_at
        assert first_stamp is not None
        # Should be very recent. SQLite drops the tz info on read so normalise
        # both sides to UTC-aware before comparing.
        if first_stamp.tzinfo is None:
            first_stamp_aware = first_stamp.replace(tzinfo=timezone.utc)
        else:
            first_stamp_aware = first_stamp
        delta = (datetime.now(timezone.utc) - first_stamp_aware).total_seconds()
        assert 0 <= delta < 5

        # Second fetch — stamp must NOT shift (idempotent).
        await client.get("/api/v1/chat/inbox")
        await db_session.refresh(before)
        assert before.first_fetched_at == first_stamp

    @pytest.mark.asyncio
    async def test_inbox_contains_own_messages_only(self, client: AsyncClient):
        # Send one message to current user (12345678)
        await client.post(
            "/api/v1/chat/send",
            json={"recipient_id": 12345678, "encrypted_payload": "for_me"},
        )
        # Send one message to someone else (should NOT appear in our inbox)
        await client.post(
            "/api/v1/chat/send",
            json={"recipient_id": 77777777, "encrypted_payload": "not_for_me"},
        )

        resp = await client.get("/api/v1/chat/inbox")
        messages = resp.json()["messages"]
        payloads = [m["encrypted_payload"] for m in messages]

        assert "for_me" in payloads
        assert "not_for_me" not in payloads

    @pytest.mark.asyncio
    async def test_inbox_ordered_by_timestamp_asc(self, client: AsyncClient):
        # Send two messages sequentially; they should come back in send order.
        for i in range(3):
            await client.post(
                "/api/v1/chat/send",
                json={"recipient_id": 12345678, "encrypted_payload": f"msg_{i}"},
            )

        resp = await client.get("/api/v1/chat/inbox")
        payloads = [m["encrypted_payload"] for m in resp.json()["messages"]]
        assert payloads == ["msg_0", "msg_1", "msg_2"]


class TestDeleteMessage:
    @pytest.mark.asyncio
    async def test_delete_own_message(self, client: AsyncClient):
        await client.post(
            "/api/v1/chat/send",
            json={"recipient_id": 12345678, "encrypted_payload": "to_delete"},
        )
        inbox = (await client.get("/api/v1/chat/inbox")).json()["messages"]
        msg_id = next(m["id"] for m in inbox if m["encrypted_payload"] == "to_delete")

        del_resp = await client.delete(f"/api/v1/chat/message/{msg_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True

        # Verify it's gone
        inbox_after = (await client.get("/api/v1/chat/inbox")).json()["messages"]
        assert msg_id not in [m["id"] for m in inbox_after]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client: AsyncClient):
        resp = await client.delete("/api/v1/chat/message/999999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"

    @pytest.mark.asyncio
    async def test_delete_other_users_message_returns_404(self, client: AsyncClient):
        """
        Send a message to user 77777777 (not the mock user). The mock user
        (12345678) should NOT be able to delete it.
        """
        # Insert a message destined for another user
        await client.post(
            "/api/v1/chat/send",
            json={"recipient_id": 77777777, "encrypted_payload": "belongs_to_other"},
        )

        # We can't easily look up the other user's inbox via the API, so we
        # query the DB directly via SQLAlchemy through the session fixture.
        # Instead, we rely on the fact that GET /inbox only shows messages for
        # 12345678 — so we need to grab the message id another way.
        # Use a high ID that won't exist for the current user's messages.
        # A simpler approach: fetch all messages from the DB via db_session.
        # Since we can't do that here easily without db_session, we'll rely on
        # the delivery test having verified sender/recipient correctness, and
        # test with an explicit DB lookup in a separate fixture-based test below.
        pass

    @pytest.mark.asyncio
    async def test_delete_other_users_message_via_db(self, client: AsyncClient, db_session):
        """Uses the db_session fixture to insert a message for user 77777777 and
        verify that the mock user (12345678) cannot delete it."""
        from app.models.models import Message

        foreign_msg = Message(
            recipient_id=77777777,
            sender_id=11111111,
            encrypted_payload="private",
        )
        db_session.add(foreign_msg)
        await db_session.flush()
        msg_id = foreign_msg.id

        resp = await client.delete(f"/api/v1/chat/message/{msg_id}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"
