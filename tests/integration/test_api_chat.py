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
