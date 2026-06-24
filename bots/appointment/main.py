import logging
from fastapi import FastAPI, Request
from .flow import handle_flow

app = FastAPI()
logger = logging.getLogger(__name__)

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    # This sub-app is mounted by main.py for diagnostics/standalone testing.
    # Production traffic is routed through whatsapp_router.py, which calls
    # bots.appointment.flow.handle_flow directly with the resolved bot + db session.
    return {"status": "ok"}
