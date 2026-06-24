# providers/meta.py
#
# Thin wrapper around the Meta Cloud API used by the router's AI-fallback path.
# The restaurant bot's full send_* functions live in
# bots/restaurant/whatsapp_handlers.py and call _send_request directly.
# This class is used by whatsapp_router.py for simple text replies only.

from __future__ import annotations

import os
import logging

import aiohttp
from session import SharedSession

logger = logging.getLogger(__name__)

WHATSAPP_TOKEN         = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
META_API_VERSION       = os.getenv("WHATSAPP_API_VERSION", "v19.0")


class MetaProvider:
    def __init__(self, bot):
        self.bot      = bot
        self.token    = (getattr(bot, "meta_token", None) or WHATSAPP_TOKEN)
        self.phone_id = (getattr(bot, "phone_number_id", None) or WHATSAPP_PHONE_NUMBER_ID)

    async def send_text(self, to: str, message: str) -> bool:
        url     = f"https://graph.facebook.com/{META_API_VERSION}/{self.phone_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        try:
            session = await SharedSession.get_session()
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"[MetaProvider] send failed {resp.status}: {text}")
                    return False
                return True
        except Exception as exc:
            logger.error(f"[MetaProvider] send exception: {exc}")
            return False

    async def send_document(self, to: str, file_path: str, filename: str, caption: str = "") -> bool:
        """
        Uploads a local file to Meta's media endpoint, then sends it as a
        WhatsApp document message. Used for PDF appointment confirmations.
        """
        upload_url = f"https://graph.facebook.com/{META_API_VERSION}/{self.phone_id}/media"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            session = await SharedSession.get_session()

            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("messaging_product", "whatsapp")
                form.add_field("type", "application/pdf")
                form.add_field("file", f, filename=filename, content_type="application/pdf")

                async with session.post(upload_url, data=form, headers=headers) as up_resp:
                    if up_resp.status >= 400:
                        text = await up_resp.text()
                        logger.error(f"[MetaProvider] media upload failed {up_resp.status}: {text}")
                        return False
                    media_data = await up_resp.json()
                    media_id = media_data.get("id")

            if not media_id:
                logger.error("[MetaProvider] media upload returned no id")
                return False

            send_url = f"https://graph.facebook.com/{META_API_VERSION}/{self.phone_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "document",
                "document": {"id": media_id, "filename": filename, "caption": caption},
            }
            headers_json = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            async with session.post(send_url, json=payload, headers=headers_json) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"[MetaProvider] send document failed {resp.status}: {text}")
                    return False
                return True
        except Exception as exc:
            logger.error(f"[MetaProvider] send_document exception: {exc}")
            return False
