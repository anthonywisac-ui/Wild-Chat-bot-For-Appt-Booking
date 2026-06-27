# manychat_router.py
#
# Synchronous bridge for ManyChat's "External Request" action. ManyChat
# (already Meta-approved, so it bypasses our own App Review/Business
# Verification wait) calls this endpoint with the subscriber id + their
# message text, and expects the bot's reply back in THE SAME HTTP response —
# unlike Meta's own APIs where we proactively push messages out.
#
# Internally this still runs the exact same bots.appointment.flow.handle_flow()
# as WhatsApp/Messenger/Instagram. The 'mc:' sender prefix makes
# whatsapp_handlers.py's send_* functions buffer their output (see
# _mc_buffer/get_and_clear_manychat_buffer in whatsapp_handlers.py) instead of
# calling an external API, and this router converts that buffer into
# ManyChat's expected response JSON.

import logging

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from db import get_db, WhatsappBot
from whatsapp_handlers import get_and_clear_manychat_buffer
from providers.wwebjs import store_menu_map, get_menu_map

router = APIRouter(tags=["ManyChat Bridge"])
logger = logging.getLogger(__name__)


def _buffer_to_manychat_response(buffered: list) -> dict:
    """Converts our internal buffer (text/buttons/list messages) into
    ManyChat's 'Dynamic Block' v2 response format, and returns a title->id
    map for the LAST interactive message (so the next reply can be translated
    back to the real button/row id even though ManyChat quick replies send
    back the tapped title, not an arbitrary payload)."""
    messages = []
    menu_map = {}

    for item in buffered:
        if item["kind"] == "text":
            if item["text"]:
                messages.append({"type": "text", "text": item["text"]})
        elif item["kind"] in ("buttons", "list"):
            options = item["options"]
            menu_map = {opt["title"]: opt["id"] for opt in options}
            lead = item.get("body") or item.get("header") or "Please choose:"
            quick_replies = [{"title": opt["title"][:20]} for opt in options[:13]]
            messages.append({"type": "text", "text": lead, "quick_replies": quick_replies})

    if not messages:
        messages = [{"type": "text", "text": "..."}]

    return {"version": "v2", "content": {"messages": messages}}, menu_map


@router.post("/manychat/webhook")
async def manychat_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Configure in ManyChat's 'External Request' action:
      Method: POST
      URL: https://<your-domain>/manychat/webhook
      Body (JSON): {"bot_id": <your bot id>, "sender": "{{user_id}}", "text": "{{last_text_input}}"}
    Then use the response's content.messages in a 'Set messages from JSON' /
    Dynamic Block step to actually display the reply.
    """
    data = await request.json()
    bot_id = data.get("bot_id")
    sender = str(data.get("sender", "")).strip()
    text = (data.get("text") or "").strip()

    if not bot_id or not sender or not text:
        return {"version": "v2", "content": {"messages": [{"type": "text", "text": "Sorry, something went wrong."}]}}

    bot = db.query(WhatsappBot).filter(WhatsappBot.id == int(bot_id)).first()
    if not bot:
        return {"version": "v2", "content": {"messages": [{"type": "text", "text": "Bot not found."}]}}

    prefixed_sender = f"mc:{sender}"

    # A quick-reply tap arrives as the tapped title text, not an id — translate
    # it back using the map saved from our last interactive message, exactly
    # like the numbered-text fallback wwebjs/Messenger/Instagram already use.
    stored_map = get_menu_map("manychat", prefixed_sender)
    if stored_map and text in stored_map:
        text = stored_map[text]

    from bots.appointment.flow import handle_flow
    await handle_flow(prefixed_sender, text, bot, db)

    buffered = get_and_clear_manychat_buffer(prefixed_sender)
    response, menu_map = _buffer_to_manychat_response(buffered)
    if menu_map:
        store_menu_map("manychat", prefixed_sender, menu_map)

    return response
