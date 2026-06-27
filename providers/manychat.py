# providers/manychat.py
#
# Direct, asynchronous push via ManyChat's "Profile Scoped Public API"
# (api.manychat.com). This is the SEND side — it lets us proactively push a
# reply to a subscriber outside the request/response cycle, matching the
# same fire-and-forget pattern providers/messenger.py and
# providers/instagram.py already use, instead of buffering a reply and
# returning it synchronously inside the incoming webhook's HTTP response
# (which risks timing out if the AI takes a moment to think).
#
# The incoming side (manychat_router.py) still relies on a ManyChat flow's
# "External Request" action to tell us a message arrived — ManyChat has no
# generic "forward every message" webhook — but the actual reply now goes
# out through this API instead of being returned in that same response.

from __future__ import annotations

import logging

import aiohttp
from session import SharedSession

logger = logging.getLogger(__name__)

API_BASE = "https://api.manychat.com"


class ManychatProvider:
    def __init__(self, bot):
        self.bot = bot
        self.token = getattr(bot, "manychat_api_key", None) or ""

    async def send_text(self, subscriber_id: str, message: str) -> bool:
        return await self._send_content(subscriber_id, {"messages": [{"type": "text", "text": message[:2000]}]})

    async def send_quick_replies(self, subscriber_id: str, text: str, buttons: list) -> bool:
        """buttons: [{"id": str, "title": str}, ...]. ManyChat quick replies
        send back the tapped TITLE as the next message (no custom payload),
        so manychat_router.py translates title -> real id via the same
        store_menu_map/get_menu_map helper the numbered-text fallback uses."""
        quick_replies = [{"title": b["title"][:20]} for b in buttons[:13]]
        return await self._send_content(subscriber_id, {
            "messages": [{"type": "text", "text": text, "quick_replies": quick_replies}]
        })

    async def send_file(self, subscriber_id: str, file_path: str, caption: str = "") -> bool:
        """ManyChat's API needs a public URL, not a local file path — we
        don't yet host one for PDFs, so this sends the caption text only as
        a best-effort fallback (the patient still gets their booking details
        in text, just not the branded PDF)."""
        return await self.send_text(subscriber_id, caption or "Your appointment is confirmed!")

    async def send_image(self, subscriber_id: str, image_url: str, caption: str = "") -> bool:
        """NOTE: ManyChat's API needs a publicly reachable URL for images —
        it can't accept a local file upload like the other providers. Pass a
        URL (e.g. one served by this app) rather than a local path."""
        if not image_url or not image_url.startswith("http"):
            return False  # a local file path was passed — nothing we can do without URL hosting
        messages = [{"type": "image", "url": image_url}]
        if caption:
            messages.append({"type": "text", "text": caption})
        return await self._send_content(subscriber_id, {"messages": messages})

    async def dispatch_payload(self, payload: dict) -> bool:
        """Accepts the same Meta-shaped interactive payload built in
        whatsapp_handlers.py and translates it for ManyChat."""
        to = payload.get("to", "")
        if not to:
            return False
        msg_type = payload.get("type", "text")

        if msg_type == "text":
            return await self.send_text(to, payload.get("text", {}).get("body", ""))

        if msg_type != "interactive":
            return False

        interactive = payload.get("interactive", {})
        itype = interactive.get("type", "")
        body_text = interactive.get("body", {}).get("text", "")
        header_text = interactive.get("header", {}).get("text", "")
        full_text = f"{header_text}\n\n{body_text}" if header_text and body_text else (header_text or body_text)

        if itype == "button":
            buttons = interactive.get("action", {}).get("buttons", [])
            quick_replies = [{"id": b["reply"]["id"], "title": b["reply"]["title"]} for b in buttons]
            return await self.send_quick_replies(to, full_text, quick_replies)

        # List-type — ManyChat has no native list UI either; reuse the same
        # numbered-text-menu fallback wwebjs/Messenger/Instagram all rely on.
        from providers.wwebjs import _meta_payload_to_text, store_menu_map
        text, menu_map = _meta_payload_to_text(payload)
        if menu_map:
            store_menu_map("manychat", to, menu_map)
        return await self.send_text(to, text)

    async def _send_content(self, subscriber_id: str, content: dict) -> bool:
        if not self.token:
            logger.error("[ManychatProvider] no manychat_api_key configured on bot")
            return False
        url = f"{API_BASE}/fb/sending/sendContent"
        payload = {
            "subscriber_id": subscriber_id,
            "data": {"version": "v2", "content": content},
            "message_tag": "ACCOUNT_UPDATE",
        }
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            session = await SharedSession.get_session()
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"[ManychatProvider] send failed {resp.status}: {text}")
                    return False
                return True
        except Exception as exc:
            logger.error(f"[ManychatProvider] send exception: {exc}")
            return False
