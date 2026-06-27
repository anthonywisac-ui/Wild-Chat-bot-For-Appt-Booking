# manychat_router.py
#
# Incoming-message bridge for ManyChat. ManyChat (already Meta-approved, so
# it bypasses our own App Review/Business Verification wait) calls this
# endpoint via a flow's "External Request" action whenever a subscriber
# messages the connected Page/Instagram account.
#
# This only handles the INCOMING side — telling us a message arrived.
# The actual reply goes OUT asynchronously through providers/manychat.py's
# direct API calls (ManychatProvider, used via the 'mc:' sender prefix in
# whatsapp_handlers.py), not through this endpoint's HTTP response. That
# avoids ManyChat's External Request timeout if the bot takes a moment to
# think — we just need to ack quickly here.

import logging

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from db import get_db, WhatsappBot
from providers.wwebjs import get_menu_map

router = APIRouter(tags=["ManyChat Bridge"])
logger = logging.getLogger(__name__)


@router.post("/manychat/webhook")
async def manychat_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Configure in ManyChat's 'External Request' action:
      Method: POST
      URL: https://<your-domain>/manychat/webhook
      Body (JSON): {"bot_id": <your bot id>, "sender": "{{user_id}}", "text": "{{last_text_input}}"}
    No further ManyChat-side step is needed — the bot's reply arrives via
    ManyChat's own messaging API directly, not through this response.
    """
    data = await request.json()
    bot_id = data.get("bot_id")
    sender = str(data.get("sender", "")).strip()
    text = (data.get("text") or "").strip()

    if not bot_id or not sender or not text:
        return {"status": "ignored"}

    bot = db.query(WhatsappBot).filter(WhatsappBot.id == int(bot_id)).first()
    if not bot:
        logger.warning(f"[manychat] no bot found for bot_id={bot_id}")
        return {"status": "ignored"}

    prefixed_sender = f"mc:{sender}"

    # A quick-reply tap arrives as the tapped TITLE text, not an id —
    # translate it back using the map saved from our last interactive
    # message, the same way the numbered-text fallback already works for
    # wwebjs/Messenger/Instagram.
    stored_map = get_menu_map("manychat", prefixed_sender)
    if stored_map and text in stored_map:
        text = stored_map[text]

    from bots.appointment.flow import handle_flow
    await handle_flow(prefixed_sender, text, bot, db)

    return {"status": "ok"}
