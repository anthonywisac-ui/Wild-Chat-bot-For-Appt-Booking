# providers/messenger.py
#
# Facebook Messenger Send API. Mirrors providers/meta.py's interface so the
# SAME bots/appointment conversation logic (which only ever calls the
# whatsapp_handlers.py send_* functions) works unchanged on this channel —
# whatsapp_handlers.py routes here whenever the recipient id is prefixed "fb:".
#
# Native quick replies are used for button-type interactives (max 3, matches
# WhatsApp's own limit). List-type interactives (WhatsApp's row lists) have no
# Messenger equivalent, so they're converted to a numbered text menu using the
# same helper wwebjs already relies on for the same reason.

from __future__ import annotations

import os
import logging

import aiohttp
from session import SharedSession

logger = logging.getLogger(__name__)

META_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v19.0")


class MessengerProvider:
    def __init__(self, bot):
        self.bot = bot
        self.token = getattr(bot, "messenger_token", None) or ""

    async def send_text(self, to: str, message: str) -> bool:
        url = f"https://graph.facebook.com/{META_API_VERSION}/me/messages"
        payload = {"recipient": {"id": to}, "message": {"text": message[:2000]}}
        return await self._post(url, payload)

    async def send_quick_replies(self, to: str, text: str, buttons: list) -> bool:
        """buttons: [{"id": str, "title": str}, ...] — max 13 quick replies on
        Messenger, title max 20 chars (same limit WhatsApp buttons already use)."""
        url = f"https://graph.facebook.com/{META_API_VERSION}/me/messages"
        payload = {
            "recipient": {"id": to},
            "message": {
                "text": text,
                "quick_replies": [
                    {"content_type": "text", "title": b["title"][:20], "payload": b["id"]}
                    for b in buttons[:13]
                ],
            },
        }
        return await self._post(url, payload)

    async def send_image(self, to: str, file_path: str, caption: str = "") -> bool:
        return await self._send_attachment(to, file_path, "image", "image/png", caption)

    async def send_file(self, to: str, file_path: str, caption: str = "") -> bool:
        """Generic file attachment — used for PDF appointment confirmations,
        since 'image' type attachments won't render a PDF correctly."""
        return await self._send_attachment(to, file_path, "file", "application/pdf", caption)

    async def _send_attachment(self, to: str, file_path: str, attach_type: str, content_type: str, caption: str = "") -> bool:
        if not file_path or not os.path.isfile(file_path):
            return False
        upload_url = f"https://graph.facebook.com/{META_API_VERSION}/me/message_attachments"
        try:
            session = await SharedSession.get_session()
            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field(
                    "message",
                    f'{{"attachment":{{"type":"{attach_type}","payload":{{"is_reusable":true}}}}}}',
                    content_type="application/json",
                )
                form.add_field("filedata", f, filename=os.path.basename(file_path), content_type=content_type)
                params = {"access_token": self.token}
                async with session.post(upload_url, data=form, params=params) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.error(f"[MessengerProvider] attachment upload failed {resp.status}: {text}")
                        return False
                    data = await resp.json()
                    attachment_id = data.get("attachment_id")
            if not attachment_id:
                return False
            send_url = f"https://graph.facebook.com/{META_API_VERSION}/me/messages"
            payload = {
                "recipient": {"id": to},
                "message": {"attachment": {"type": attach_type, "payload": {"attachment_id": attachment_id}}},
            }
            ok = await self._post(send_url, payload)
            if ok and caption:
                await self.send_text(to, caption)
            return ok
        except Exception as exc:
            logger.error(f"[MessengerProvider] send_image exception: {exc}")
            return False

    async def dispatch_payload(self, payload: dict) -> bool:
        """Accepts the same Meta-shaped interactive payload built in
        whatsapp_handlers.py and translates it for Messenger."""
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

        # List-type — no Messenger equivalent, fall back to numbered text menu.
        from providers.wwebjs import _meta_payload_to_text, store_menu_map
        text, menu_map = _meta_payload_to_text(payload)
        if menu_map:
            store_menu_map("messenger", to, menu_map)
        return await self.send_text(to, text)

    async def _post(self, url: str, payload: dict) -> bool:
        try:
            session = await SharedSession.get_session()
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"[MessengerProvider] send failed {resp.status}: {text}")
                    return False
                return True
        except Exception as exc:
            logger.error(f"[MessengerProvider] send exception: {exc}")
            return False
