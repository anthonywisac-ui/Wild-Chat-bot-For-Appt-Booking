from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel
import os
import json
import logging
import requests

from auth import get_current_user, require_admin
from db import (
    get_db, User, WhatsappBot, Contact, Deal, Call, VapiAgent, AuditLog, BotConfigAudit, AdminSetting,
    ChatHistory, BotEventLog, log_bot_event, Reservation, SaleRecord, BotPlugin, Appointment, Doctor, Lead,
    Procedure, PatientProfile, BotCollaborator, get_user_by_username, create_user,
    create_doctor, update_doctor, delete_doctor, get_doctor_by_id,
    create_procedure, update_procedure, delete_procedure, get_procedure_by_id,
    create_appointment,
)

router = APIRouter(prefix="/api/crm", tags=["CRM"])
logger = logging.getLogger(__name__)
# ── Utils ── (Bug #8)
def mask_sensitive(val: str):
    if not val or len(val) < 8: return "****"
    return f"{val[:2]}****{val[-2:]}"

def log_audit(db: Session, user_id: int, action: str, details: str):
    new_log = AuditLog(user_id=user_id, action=action, details=details)
    db.add(new_log)
    try: db.commit()
    except: db.rollback()

def validate_bot_credentials(bot_id: int, db: Session):
    """Bug #4: Validation workflow for bots"""
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id).first()
    if not bot: return
    
    bot.status = "validating"
    db.commit()
    
    errors = []
    # WhatsApp Check
    if bot.meta_token and bot.phone_number_id:
        url = f"https://graph.facebook.com/v18.0/{bot.phone_number_id}"
        headers = {"Authorization": f"Bearer {bot.meta_token}"}
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code != 200: errors.append(f"Meta API Error ({r.status_code})")
        except: errors.append("Meta connection failed")
    
    # AI Check
    if bot.ai_provider == "groq" and bot.groq_api_key:
        headers = {"Authorization": f"Bearer {bot.groq_api_key}"}
        try:
            r = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=5)
            if r.status_code != 200: errors.append(f"Groq API Error ({r.status_code})")
        except: errors.append("Groq connection failed")
    
    bot.status = "error" if errors else "active"
    bot.last_health_check = datetime.utcnow()
    db.commit()
    
    if errors:
        log_audit(db, bot.owner_id, "BOT_VALIDATION_FAILED", f"Bot {bot.name} failed validation: {', '.join(errors)}")
    else:
        log_audit(db, bot.owner_id, "BOT_VALIDATION_SUCCESS", f"Bot {bot.name} validated successfully")

# ========== Pydantic Models ==========
class ContactCreate(BaseModel):
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    company: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    status: Optional[str] = "New"
    source: Optional[str] = "Manual"
    notes: Optional[str] = ""

class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None

class DealCreate(BaseModel):
    title: str = "New Deal"
    company: Optional[str] = ""
    contact_name: Optional[str] = ""
    value: float = 0.0
    stage: str = "Discovery"
    probability: int = 20
    expected_close: Optional[datetime] = None
    notes: Optional[str] = ""

class DealUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    contact_name: Optional[str] = None
    value: Optional[float] = None
    stage: Optional[str] = None
    probability: Optional[int] = None
    expected_close: Optional[datetime] = None
    notes: Optional[str] = None

class CallCreate(BaseModel):
    contact_name: str = "Unknown"
    phone: str = ""
    direction: str = "Inbound"
    duration_minutes: float = 0.0
    outcome: str = "Resolved"
    agent: str = ""
    notes: Optional[str] = ""

class VapiAgentCreate(BaseModel):
    name: str
    vapi_api_key: str
    vapi_agent_id: str
    phone_number_id: Optional[str] = None
    first_message: str
    system_prompt: str
    voice: str = "Alloy"
    crm_sync: bool = False
    webhook_url: str

class WhatsappBotCreate(BaseModel):
    name: str
    bot_type: str
    business_name: Optional[str] = None
    language: Optional[str] = "en"
    meta_token: Optional[str] = None
    phone_number_id: Optional[str] = None
    waba_id: Optional[str] = None
    verify_token: Optional[str] = None
    manager_number: Optional[str] = None
    ai_provider: Optional[str] = "gemini"
    ai_api_key: Optional[str] = None
    system_prompt: Optional[str] = None
    google_sheet_id: Optional[str] = None
    google_creds_json: Optional[str] = None
    stripe_secret_key: Optional[str] = None
    webhook_url: Optional[str] = None
    vapi_agent_id: Optional[str] = None

class ChatRequest(BaseModel):
    messages: list

class UserConfigSave(BaseModel):
    ai_provider: str
    groq_api_key: Optional[str] = ""
    gemini_api_key: Optional[str] = ""
    openai_api_key: Optional[str] = ""
    minimax_api_key: Optional[str] = ""
    anthropic_api_key: Optional[str] = ""
    openrouter_api_key: Optional[str] = ""
    openrouter_model: Optional[str] = "nousresearch/hermes-3-llama-3.1-405b:free"
    default_voice: Optional[str] = "Alloy"
    default_first_message: Optional[str] = "Hello, how can I help you?"

class ReservationCreate(BaseModel):
    customer_name: str = ""
    customer_phone: str = ""
    party_size: int = 2
    reservation_date: str = ""
    reservation_time: str = ""
    notes: Optional[str] = ""

# ========== Contacts ==========
@router.get("/contacts")
def get_contacts_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_contacts(db, current_user.id)

@router.post("/contacts")
def create_contact_api(contact: ContactCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_contact = create_contact(db, current_user.id, contact.dict())
    log_audit(db, current_user.id, "CREATE_CONTACT", f"Contact created: {new_contact.first_name} {new_contact.last_name}")
    return new_contact

@router.put("/contacts/{contact_id}")
def update_contact_api(contact_id: int, contact: ContactUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_contact = db.query(Contact).filter(Contact.id == contact_id, Contact.owner_id == current_user.id).first()
    if not db_contact:
        raise HTTPException(404, "Contact not found")
    update_data = contact.dict(exclude_unset=True)
    allowed_fields = {"first_name", "last_name", "company", "email", "phone", "status", "source", "notes"}
    for key, value in update_data.items():
        if key in allowed_fields:
            setattr(db_contact, key, value)
    db.commit()
    db.refresh(db_contact)
    log_audit(db, current_user.id, "UPDATE_CONTACT", f"Updated contact: {db_contact.first_name} {db_contact.last_name}")
    return db_contact

# ========== Deals ==========
@router.get("/deals")
def get_deals_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_deals(db, current_user.id)

@router.post("/deals")
def create_deal_api(deal: DealCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_deal = create_deal(db, current_user.id, deal.dict())
    log_audit(db, current_user.id, "CREATE_DEAL", f"Deal created: {new_deal.title}")
    return new_deal

# ========== Calls ==========
@router.get("/calls")
def get_calls_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_calls(db, current_user.id)

# ========== Vapi Agents ==========
@router.get("/vapi/agents")
def get_vapi_agents_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agents = db.query(VapiAgent).filter(VapiAgent.owner_id == current_user.id).all()
    return [{
        "id": a.id, "name": a.name, "status": a.status,
        "last_call": a.last_call.isoformat() if a.last_call else None,
        "total_calls": a.total_calls, "conversion_rate": a.conversion_rate
    } for a in agents]

@router.post("/vapi/agents")
def create_vapi_agent_api(agent_data: VapiAgentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.query(VapiAgent).filter(VapiAgent.owner_id == current_user.id, VapiAgent.name == agent_data.name).first()
    if existing:
        raise HTTPException(400, "Agent name already exists")
    new_agent = VapiAgent(owner_id=current_user.id, **agent_data.dict(), status="Draft")
    db.add(new_agent)
    db.commit()
    log_audit(db, current_user.id, "CREATE_VAPI_AGENT", f"VAPI Agent created: {new_agent.name}")
    return {"id": new_agent.id, "message": "Agent created"}

# ========== WhatsApp Bots ==========
def _bots_visible_to(current_user: User, db: Session):
    """A user sees bots they own AND bots they've been added to as a team
    collaborator (see BotCollaborator / the Team page)."""
    collab_bot_ids = [c.bot_id for c in db.query(BotCollaborator).filter(BotCollaborator.user_id == current_user.id).all()]
    return db.query(WhatsappBot).filter(
        (WhatsappBot.owner_id == current_user.id) | (WhatsappBot.id.in_(collab_bot_ids))
    ).all()

@router.get("/bots/whatsapp")
def get_my_bots(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bots = _bots_visible_to(current_user, db)
    return [{
        "id": b.id,
        "name": b.name,
        "bot_type": b.bot_type,
        "business_name": b.business_name,
        "language": b.language,
        "webhook_url": b.webhook_url,
        "config_json": b.config_json,
        "tax_rate": b.tax_rate,
        "delivery_fee": b.delivery_fee,
        "meta_token": mask_sensitive(b.meta_token),
        "phone_number_id": b.phone_number_id,
        "waba_id": b.waba_id,
        "verify_token": b.verify_token,
        "manager_number": b.manager_number,
        "ai_provider": b.ai_provider,
        "ai_api_key": mask_sensitive(b.ai_api_key),
        "system_prompt": b.system_prompt,
        "provider": b.provider,
        "wwebjs_session": b.wwebjs_session,
        "messenger_page_id": b.messenger_page_id,
        "instagram_account_id": b.instagram_account_id,
        "manychat_api_key": mask_sensitive(b.manychat_api_key) if b.manychat_api_key else None,
        "is_owner": b.owner_id == current_user.id,
        "created_at": b.created_at.isoformat() if b.created_at else None
    } for b in bots]

@router.post("/bots/whatsapp")
def create_whatsapp_bot_endpoint(bot_data: WhatsappBotCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # ✅ FIX: Check globally for name uniqueness to avoid IntegrityError (500)
    existing = db.query(WhatsappBot).filter(WhatsappBot.name == bot_data.name).first()
    if existing:
        raise HTTPException(400, f"Bot name '{bot_data.name}' is already taken by another bot.")
    
    new_bot = WhatsappBot(
        owner_id=current_user.id,
        name=bot_data.name,
        bot_type=bot_data.bot_type,
        business_name=bot_data.business_name or "",
        language=bot_data.language or "en",
        meta_token=bot_data.meta_token or "",
        phone_number_id=bot_data.phone_number_id or "",
        waba_id=bot_data.waba_id or "",
        verify_token=bot_data.verify_token or "",
        manager_number=bot_data.manager_number or "",
        ai_provider=bot_data.ai_provider or "gemini",
        ai_api_key=bot_data.ai_api_key or "",
        system_prompt=bot_data.system_prompt or "",
        webhook_url=bot_data.webhook_url or ""
    )
    db.add(new_bot)
    try:
        db.commit()
        db.refresh(new_bot)
        
        # Update user's bot list
        user_bots = current_user.bots
        if bot_data.name not in user_bots:
            user_bots.append(bot_data.name)
            current_user.bots = user_bots
            db.commit()
        
        log_audit(db, current_user.id, "CREATE_BOT", f"Bot created: {new_bot.name}")
        log_bot_event(new_bot.id, "BOT_CREATED", f"Bot created by {current_user.username} | type={new_bot.bot_type}")
        
        # Bug #4: Run validation immediately
        validate_bot_credentials(new_bot.id, db)
        
        return {"id": new_bot.id, "message": "Bot created successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create bot: {str(e)}")
        raise HTTPException(500, "Could not create bot record.")

@router.put("/bots/whatsapp/{bot_id}")
def update_bot_api(bot_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")

    # Bug #3: Rate Limiting (10 requests per minute)
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    recent_updates = db.query(BotConfigAudit).filter(
        BotConfigAudit.bot_id == bot_id,
        BotConfigAudit.created_at > one_minute_ago
    ).count()
    if recent_updates >= 10:
        raise HTTPException(429, "Rate limit exceeded. Max 10 updates per minute.")

    # Bug #1: Expanded Allowed Fields
    allowed = {
        "name", "bot_type", "business_name", "language", "meta_token",
        "phone_number_id", "waba_id", "verify_token", "manager_number",
        "ai_provider", "ai_api_key", "system_prompt", "webhook_url",
        "config_json", "tax_rate", "delivery_fee", "business_niche", "vapi_agent_id",
        "vapi_api_key", "openai_api_key", "gemini_api_key", "groq_api_key", "minimax_api_key", "anthropic_api_key",
        "forwarding_url",
        "messenger_page_id", "messenger_token", "instagram_account_id", "instagram_token",
        "manychat_api_key",
    }

    try:
        changes = []
        for k, v in data.items():
            if k in allowed:
                old_val = str(getattr(bot, k))
                new_val = str(v)

                if old_val != new_val:
                    # Bug #2 & #8: Log Config Audit with masking
                    is_sensitive = k in ["meta_token", "ai_api_key", "vapi_api_key", "openai_api_key", "gemini_api_key", "groq_api_key", "minimax_api_key", "anthropic_api_key", "openrouter_api_key", "messenger_token", "instagram_token", "manychat_api_key"]
                    audit = BotConfigAudit(
                        bot_id=bot.id, user_id=current_user.id,
                        field=k, 
                        old_value=mask_sensitive(old_val) if is_sensitive else old_val,
                        new_value=mask_sensitive(new_val) if is_sensitive else new_val
                    )
                    db.add(audit)
                    setattr(bot, k, v)
                    changes.append(k)

        if changes:
            # Bug #9: Proper Transaction Management
            db.commit()
            db.refresh(bot)
            log_audit(db, current_user.id, "UPDATE_BOT", f"Updated {bot.name} fields: {', '.join(changes)}")
            log_bot_event(bot.id, "CONFIG_UPDATED", f"Fields changed: {', '.join(changes)} | by {current_user.username}")
            if "config_json" in changes and bot.bot_type == "restaurant":
                try:
                    from bots.restaurant.db import invalidate_menu_cache
                    invalidate_menu_cache(phone_number_id=bot.phone_number_id, bot_id=bot.id)
                except Exception:
                    pass

        return {"status": "updated", "id": bot.id, "changes": changes}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating bot {bot_id}: {str(e)}")
        raise HTTPException(500, "Failed to update bot configuration.")

@router.post("/bots/whatsapp/{bot_id}/duplicate")
def duplicate_bot(bot_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    original = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not original:
        raise HTTPException(404, "Original bot not found")
    
    new_name = f"{original.name} (Copy)"
    # Ensure global uniqueness
    count = 1
    while db.query(WhatsappBot).filter(WhatsappBot.name == new_name).first():
        new_name = f"{original.name} (Copy {count})"
        count += 1

    new_bot = WhatsappBot(
        owner_id=current_user.id,
        name=new_name,
        bot_type=original.bot_type,
        business_name=original.business_name,
        business_niche=original.business_niche,
        language=original.language,
        config_json=original.config_json,
        tax_rate=original.tax_rate,
        delivery_fee=original.delivery_fee,
        system_prompt=original.system_prompt,
        ai_provider=original.ai_provider,
        ai_api_key=original.ai_api_key,
        manager_number=original.manager_number,
        meta_token="",
        phone_number_id="",
        waba_id="",
        verify_token="",
        status="pending_config"
    )
    db.add(new_bot)
    db.commit()
    db.refresh(new_bot)
    
    log_audit(db, current_user.id, "DUPLICATE_BOT", f"Duplicated bot {original.name} to {new_name}")
    log_bot_event(new_bot.id, "BOT_DUPLICATED", f"Cloned from '{original.name}' by {current_user.username}")
    return {"id": new_bot.id, "message": "Bot duplicated successfully", "new_name": new_name}

@router.get("/bots/whatsapp/{bot_id}/effective-menu")
def get_effective_menu(bot_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the bot's active menu in builder format, falling back to default menu."""
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    try:
        from bots.restaurant.db import get_bot_menu
        menu = get_bot_menu(phone_number_id=bot.phone_number_id or None, bot_id=bot.id)
        categories = []
        for cat_key, cat_data in menu.items():
            items_dict = cat_data.get("items", {})
            items = [
                {"id": iid, "name": v.get("name",""), "price": v.get("price",0),
                 "emoji": v.get("emoji","📦"), "desc": v.get("desc",""), "addons": v.get("addons","")}
                for iid, v in items_dict.items()
            ]
            first_id = next(iter(items_dict), "")
            prefix = ''.join(c for c in first_id if c.isalpha())[:4]
            categories.append({"id": f"cat_{cat_key}", "name": cat_data.get("name", cat_key.title()),
                                "prefix": prefix, "type": "normal", "items": items})
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(500, f"Could not load menu: {e}")

@router.get("/bots/whatsapp/{bot_id}/event-logs")
def get_bot_event_logs(bot_id: int, limit: int = 200, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch event log for a specific bot. Accessible by owner or admin."""
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    if bot.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Not authorized")
    logs = (db.query(BotEventLog)
              .filter(BotEventLog.bot_id == bot_id)
              .order_by(BotEventLog.created_at.desc())
              .limit(min(limit, 500))
              .all())
    return [{
        "id": l.id,
        "event_type": l.event_type,
        "details": l.details,
        "customer_phone": l.customer_phone,
        "created_at": l.created_at.isoformat(),
    } for l in logs]

@router.post("/activity-log")
def log_frontend_activity(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Log frontend UI events to audit log."""
    action = data.get("action", "UI_EVENT")[:64]
    details = data.get("details", "")[:512]
    log_audit(db, current_user.id, action, details)
    return {"ok": True}

@router.delete("/bots/whatsapp/{bot_id}")
def delete_bot_api(bot_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    bot_name = bot.name
    
    # Remove from user's bot list (Bug #Sync)
    user_bots = current_user.bots
    if bot_name in user_bots:
        user_bots.remove(bot_name)
        current_user.bots = user_bots
    
    log_bot_event(bot.id, "BOT_DELETED", f"Bot '{bot_name}' deleted by {current_user.username}")
    db.delete(bot)
    db.commit()
    log_audit(db, current_user.id, "DELETE_BOT", f"Bot deleted: {bot_name}")
    return {"status": "deleted"}

# ========== Appointments / Leads / Doctors (owner-scoped, for the dashboard) ==========
def _get_owned_bot(bot_id: int, current_user: User, db: Session) -> WhatsappBot:
    """A bot is accessible to its owner AND any user added as a team
    collaborator (see BotCollaborator / the Team page) — same data either way."""
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if bot:
        return bot
    is_collaborator = db.query(BotCollaborator).filter(
        BotCollaborator.bot_id == bot_id, BotCollaborator.user_id == current_user.id
    ).first()
    if is_collaborator:
        bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id).first()
        if bot:
            return bot
    raise HTTPException(404, "Bot not found")

class AppointmentCreateBody(BaseModel):
    customer_name: str
    customer_phone: str
    department: str
    appointment_date: str
    appointment_time: str
    procedure_id: Optional[int] = None
    doctor_id: Optional[int] = None
    consultation_fee: float = 0.0
    service: Optional[str] = None

@router.post("/bots/{bot_id}/appointments")
def create_appointment_api(
    bot_id: int, body: AppointmentCreateBody,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Lets clinic staff book a walk-in/phone-call appointment directly from
    the dashboard — previously the only way to create an Appointment row was
    through the WhatsApp bot flow itself. Mirrors db.create_appointment(),
    the same helper the bot uses, so manually-booked and bot-booked
    appointments behave identically everywhere else (Reports, Payments, etc.)."""
    _get_owned_bot(bot_id, current_user, db)
    service_name = body.service
    if not service_name and body.procedure_id:
        proc = db.query(Procedure).filter(Procedure.id == body.procedure_id, Procedure.bot_id == bot_id).first()
        if proc:
            service_name = proc.name
    appt = create_appointment(
        db, owner_id=current_user.id, bot_id=bot_id,
        customer_phone=body.customer_phone, customer_name=body.customer_name,
        service=service_name or "Consultation", department=body.department,
        doctor_id=body.doctor_id, consultation_fee=body.consultation_fee,
        procedure_id=body.procedure_id,
        appointment_date=body.appointment_date, appointment_time=body.appointment_time,
    )
    return {
        "id": appt.id, "customer_name": appt.customer_name, "customer_phone": appt.customer_phone,
        "service": appt.service, "department": appt.department, "status": appt.status,
        "appointment_date": appt.appointment_date, "appointment_time": appt.appointment_time,
        "consultation_fee": appt.consultation_fee,
    }

@router.get("/bots/{bot_id}/appointments")
def list_appointments_api(
    bot_id: int,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    q = db.query(Appointment).filter(Appointment.bot_id == bot_id)
    if status:
        q = q.filter(Appointment.status == status)
    if date_from:
        q = q.filter(Appointment.appointment_date >= date_from)
    if date_to:
        q = q.filter(Appointment.appointment_date <= date_to)
    total = q.count()
    rows = q.order_by(Appointment.appointment_date, Appointment.appointment_time).offset(offset).limit(min(limit, 200)).all()

    doctor_ids = {r.doctor_id for r in rows if r.doctor_id}
    doctors_by_id = {d.id: d.name for d in db.query(Doctor).filter(Doctor.id.in_(doctor_ids)).all()} if doctor_ids else {}

    return {
        "total": total,
        "appointments": [
            {
                "id": r.id,
                "customer_name": r.customer_name,
                "customer_phone": r.customer_phone,
                "service": r.service,
                "department": r.department,
                "doctor_name": doctors_by_id.get(r.doctor_id),
                "appointment_date": r.appointment_date,
                "appointment_time": r.appointment_time,
                "status": r.status,
                "consultation_fee": r.consultation_fee,
            }
            for r in rows
        ],
    }

class AppointmentStatusUpdate(BaseModel):
    status: Optional[str] = None
    reminder_sent: Optional[bool] = None

@router.patch("/bots/{bot_id}/appointments/{appointment_id}")
def update_appointment_status_api(
    bot_id: int,
    appointment_id: int,
    body: AppointmentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    appt = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.bot_id == bot_id).first()
    if not appt:
        raise HTTPException(404, "Appointment not found")
    if body.status is not None:
        appt.status = body.status
    if body.reminder_sent is not None:
        appt.reminder_sent = body.reminder_sent
    appt.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "updated", "id": appt.id, "new_status": appt.status, "reminder_sent": appt.reminder_sent}

@router.get("/bots/{bot_id}/leads")
def list_leads_api(
    bot_id: int,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    q = db.query(Lead).filter(Lead.bot_id == bot_id)
    if status:
        q = q.filter(Lead.status == status)
    rows = q.order_by(Lead.created_at.desc()).limit(200).all()
    return [
        {
            "id": r.id,
            "phone": r.phone,
            "goal": r.goal,
            "concern": r.concern,
            "treatment_interest": r.treatment_interest,
            "budget_level": r.budget_level,
            "lead_quality": r.lead_quality,
            "status": r.status,
            "estimated_value": r.estimated_value,
            "created_at": r.created_at,
        }
        for r in rows
    ]

@router.get("/bots/{bot_id}/doctors")
def list_doctors_api(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    rows = db.query(Doctor).filter(Doctor.bot_id == bot_id, Doctor.active == True).all()
    return [
        {
            "id": r.id,
            "department": r.department,
            "name": r.name,
            "gender": r.gender,
            "bio": r.bio,
            "consultation_fee": r.consultation_fee,
        }
        for r in rows
    ]

class DoctorBody(BaseModel):
    department: str
    name: str
    gender: str = ""
    bio: str = ""
    consultation_fee: float = 0.0

class DoctorUpdateBody(BaseModel):
    department: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[str] = None
    bio: Optional[str] = None
    consultation_fee: Optional[float] = None

def _doctor_dict(r: Doctor) -> dict:
    return {
        "id": r.id, "department": r.department, "name": r.name,
        "gender": r.gender, "bio": r.bio, "consultation_fee": r.consultation_fee,
    }

@router.post("/bots/{bot_id}/doctors")
def create_doctor_api(
    bot_id: int, body: DoctorBody,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    doc = create_doctor(
        db, bot_id=bot_id, department=body.department, name=body.name,
        gender=body.gender, bio=body.bio, consultation_fee=body.consultation_fee,
    )
    return _doctor_dict(doc)

@router.put("/bots/{bot_id}/doctors/{doctor_id}")
def update_doctor_api(
    bot_id: int, doctor_id: int, body: DoctorUpdateBody,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    doc = get_doctor_by_id(db, bot_id, doctor_id)
    if not doc:
        raise HTTPException(404, "Doctor not found")
    doc = update_doctor(db, doc, body.dict(exclude_unset=True))
    return _doctor_dict(doc)

@router.delete("/bots/{bot_id}/doctors/{doctor_id}")
def delete_doctor_api(
    bot_id: int, doctor_id: int,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    doc = get_doctor_by_id(db, bot_id, doctor_id)
    if not doc:
        raise HTTPException(404, "Doctor not found")
    delete_doctor(db, doc)
    return {"status": "deleted"}

@router.get("/bots/{bot_id}/procedures")
def list_procedures_api(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    rows = db.query(Procedure).filter(Procedure.bot_id == bot_id, Procedure.active == True).all()
    return [
        {
            "id": r.id,
            "department": r.department,
            "name": r.name,
            "sessions_required": r.sessions_required,
            "fee_per_session": r.fee_per_session,
            "package_tier": r.package_tier,
            "description": r.description,
        }
        for r in rows
    ]

class ProcedureBody(BaseModel):
    department: str
    name: str
    sessions_required: int = 1
    fee_per_session: float = 0.0
    package_tier: str = ""
    description: str = ""

class ProcedureUpdateBody(BaseModel):
    department: Optional[str] = None
    name: Optional[str] = None
    sessions_required: Optional[int] = None
    fee_per_session: Optional[float] = None
    package_tier: Optional[str] = None
    description: Optional[str] = None

def _procedure_dict(r: Procedure) -> dict:
    return {
        "id": r.id, "department": r.department, "name": r.name,
        "sessions_required": r.sessions_required, "fee_per_session": r.fee_per_session,
        "package_tier": r.package_tier, "description": r.description,
    }

@router.post("/bots/{bot_id}/procedures")
def create_procedure_api(
    bot_id: int, body: ProcedureBody,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    proc = create_procedure(
        db, bot_id=bot_id, department=body.department, name=body.name,
        sessions_required=body.sessions_required, fee_per_session=body.fee_per_session,
        description=body.description, package_tier=body.package_tier,
    )
    return _procedure_dict(proc)

@router.put("/bots/{bot_id}/procedures/{procedure_id}")
def update_procedure_api(
    bot_id: int, procedure_id: int, body: ProcedureUpdateBody,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    proc = get_procedure_by_id(db, bot_id, procedure_id)
    if not proc:
        raise HTTPException(404, "Procedure not found")
    proc = update_procedure(db, proc, body.dict(exclude_unset=True))
    return _procedure_dict(proc)

@router.delete("/bots/{bot_id}/procedures/{procedure_id}")
def delete_procedure_api(
    bot_id: int, procedure_id: int,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    proc = get_procedure_by_id(db, bot_id, procedure_id)
    if not proc:
        raise HTTPException(404, "Procedure not found")
    delete_procedure(db, proc)
    return {"status": "deleted"}

@router.get("/bots/{bot_id}/patients")
def list_patients_api(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(bot_id, current_user, db)
    rows = db.query(PatientProfile).filter(PatientProfile.bot_id == bot_id).order_by(PatientProfile.created_at.desc()).limit(200).all()
    return [
        {
            "id": r.id,
            "phone": r.phone,
            "name": r.name,
            "age": r.age,
            "gender": r.gender,
            "city": r.city,
            "created_at": r.created_at,
        }
        for r in rows
    ]

# ========== Demo data seeding (owner-triggered, idempotent by name) ==========
_DEMO_DEPARTMENTS = {
    "skin": {
        "doctors": [("Dr Laila Khan", "female", 60), ("Dr Hamid Raza", "male", 55)],
        "procedures": [
            ("HydraFacial", 1, 80, None),
            ("Chemical Peel", 1, 65, None),
            ("Acne Treatment Package", 6, 50, "package"),
        ],
    },
    "hair": {
        "doctors": [("Dr Sara Naveed", "female", 60)],
        "procedures": [
            ("PRP Hair Therapy", 4, 120, "package"),
            ("Hair Loss Consultation", 1, 40, None),
        ],
    },
    "laser": {
        "doctors": [("Dr Omar Faisal", "male", 55)],
        "procedures": [
            ("Laser Hair Removal - Full Body", 6, 90, "package"),
            ("Laser Hair Removal - Underarms", 4, 35, "package"),
        ],
    },
    "body": {
        "doctors": [("Dr Ayesha Tariq", "female", 65)],
        "procedures": [
            ("Body Contouring", 4, 150, "package"),
            ("Cellulite Reduction", 6, 100, "package"),
        ],
    },
    "dental": {
        "doctors": [("Dr Jamshed Ali", "male", 50)],
        "procedures": [
            ("Teeth Whitening", 1, 70, None),
            ("Smile Design", 1, 300, None),
            ("Dental Cleaning", 1, 30, None),
        ],
    },
    "injectables": {
        "doctors": [("Dr Sara Naveed", "female", 60)],
        "procedures": [
            ("Lip Fillers", 1, 200, None),
            ("Botox", 1, 250, None),
        ],
    },
}

_DEMO_PATIENTS = [
    ("Sara Khan", "+971501234567", 29, "female", "Dubai"),
    ("Mohammed Ali", "+971502345678", 34, "male", "Abu Dhabi"),
    ("Rabia Hussain", "+971503456789", 27, "female", "Dubai"),
    ("Ayesha Malik", "+971504567890", 31, "female", "Sharjah"),
    ("Hamza Zubair", "+971505678901", 38, "male", "Dubai"),
    ("Fatima Noor", "+971506789012", 24, "female", "Dubai"),
    ("Bilal Ahmed", "+971507890123", 41, "male", "Ajman"),
]

@router.post("/bots/{bot_id}/seed-demo-data")
def seed_demo_data_api(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One-time, idempotent seed of doctors/procedures across every department
    plus a spread of leads/patients/appointments so a fresh dashboard has
    something real to show in a client demo. Safe to call more than once —
    skips any doctor/procedure that already exists by name, and only ADDS
    leads/appointments, never deletes existing ones."""
    bot = _get_owned_bot(bot_id, current_user, db)

    import random
    random.seed(bot_id)  # deterministic-ish spread across repeated calls

    doctors_created, procedures_created = 0, 0
    doctor_by_name: dict[str, Doctor] = {}
    procedures_by_dept: dict[str, list[Procedure]] = {}

    for dept, cfg in _DEMO_DEPARTMENTS.items():
        for name, gender, fee in cfg["doctors"]:
            existing = db.query(Doctor).filter(Doctor.bot_id == bot_id, Doctor.name == name).first()
            if not existing:
                existing = Doctor(bot_id=bot_id, department=dept, name=name, gender=gender, consultation_fee=fee, active=True)
                db.add(existing)
                db.commit()
                db.refresh(existing)
                doctors_created += 1
            doctor_by_name[name] = existing

        procedures_by_dept[dept] = []
        for name, sessions, fee, tier in cfg["procedures"]:
            existing = db.query(Procedure).filter(Procedure.bot_id == bot_id, Procedure.name == name).first()
            if not existing:
                existing = Procedure(
                    bot_id=bot_id, department=dept, name=name,
                    sessions_required=sessions, fee_per_session=fee,
                    package_tier=tier, active=True,
                )
                db.add(existing)
                db.commit()
                db.refresh(existing)
                procedures_created += 1
            procedures_by_dept[dept].append(existing)

    patients_created = 0
    for name, phone, age, gender, city in _DEMO_PATIENTS:
        existing = db.query(PatientProfile).filter(PatientProfile.bot_id == bot_id, PatientProfile.phone == phone).first()
        if not existing:
            db.add(PatientProfile(bot_id=bot_id, phone=phone, name=name, age=str(age), gender=gender, city=city))
            patients_created += 1
    db.commit()

    lead_qualities = ["high", "medium", "low"]
    lead_statuses = ["new", "qualified", "booked", "lost"]
    leads_created = 0
    for name, phone, age, gender, city in _DEMO_PATIENTS:
        if db.query(Lead).filter(Lead.bot_id == bot_id, Lead.phone == phone).first():
            continue
        dept = random.choice(list(_DEMO_DEPARTMENTS.keys()))
        proc = random.choice(procedures_by_dept[dept])
        db.add(Lead(
            bot_id=bot_id, phone=phone, goal="booking",
            concern=f"Interested in {proc.name}", treatment_interest=proc.name,
            budget_level=random.choice(["low", "medium", "high"]),
            lead_quality=random.choice(lead_qualities),
            status=random.choice(lead_statuses),
            estimated_value=proc.fee_per_session * proc.sessions_required,
        ))
        leads_created += 1
    db.commit()

    appt_statuses_weighted = ["Confirmed"] * 5 + ["Completed"] * 3 + ["Scheduled"] * 2 + ["Cancelled"]
    appointments_created = 0
    today = datetime.utcnow().date()
    for day_offset in range(-7, 8):
        day = today + timedelta(days=day_offset)
        # Guarantee today and tomorrow always get a few bookings — a random
        # 0-2 roll could land on zero and make the Overview dashboard look
        # empty ("$0 revenue today") right after seeding, which defeats the
        # point of seeding it for a demo.
        count = random.randint(2, 3) if day_offset in (0, 1) else random.randint(0, 2)
        for _ in range(count):
            patient_name, phone, age, gender, city = random.choice(_DEMO_PATIENTS)
            dept = random.choice(list(_DEMO_DEPARTMENTS.keys()))
            proc = random.choice(procedures_by_dept[dept])
            doc = doctor_by_name[random.choice(_DEMO_DEPARTMENTS[dept]["doctors"])[0]]
            hour = random.choice([10, 11, 13, 14, 15, 16, 17])
            db.add(Appointment(
                owner_id=current_user.id, bot_id=bot_id,
                customer_phone=phone, customer_name=patient_name,
                service=proc.name, department=dept, doctor_id=doc.id, procedure_id=proc.id,
                consultation_fee=proc.fee_per_session,
                appointment_date=day.strftime("%Y-%m-%d"),
                appointment_time=f"{hour:02d}:00",
                status=random.choice(["Confirmed", "Confirmed", "Scheduled"]) if day_offset >= 0 else random.choice(appt_statuses_weighted),
                reminder_sent=day_offset < 0,
            ))
            appointments_created += 1
    db.commit()

    return {
        "message": "Demo data seeded",
        "doctors_created": doctors_created,
        "procedures_created": procedures_created,
        "patients_created": patients_created,
        "leads_created": leads_created,
        "appointments_created": appointments_created,
    }

# ========== Team (bot collaborators) ==========
class TeamMemberCreate(BaseModel):
    username: str
    password: str

@router.get("/bots/{bot_id}/team")
def list_team_api(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _get_owned_bot(bot_id, current_user, db)
    owner = db.query(User).filter(User.id == bot.owner_id).first()
    collaborators = db.query(BotCollaborator).filter(BotCollaborator.bot_id == bot_id).all()
    collaborator_users = {u.id: u for u in db.query(User).filter(User.id.in_([c.user_id for c in collaborators])).all()} if collaborators else {}
    members = [{"user_id": owner.id, "username": owner.username, "role": "owner"}]
    for c in collaborators:
        u = collaborator_users.get(c.user_id)
        if u:
            members.append({"user_id": u.id, "username": u.username, "role": "member", "added_at": c.created_at})
    return members

@router.post("/bots/{bot_id}/team")
def add_team_member_api(
    bot_id: int,
    body: TeamMemberCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner-only: create a login for a team member (or reuse an existing
    user) and grant them access to this bot's dashboard data. New accounts
    are always created with role='user' — never 'admin' — regardless of who
    creates them."""
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found, or you're not the owner")

    member = get_user_by_username(db, body.username)
    if not member:
        member = create_user(db, body.username, body.password, role="user")
        if not member:
            raise HTTPException(400, "Could not create user")
    elif member.id == current_user.id:
        raise HTTPException(400, "You already have access to this bot")

    existing = db.query(BotCollaborator).filter(BotCollaborator.bot_id == bot_id, BotCollaborator.user_id == member.id).first()
    if not existing:
        db.add(BotCollaborator(bot_id=bot_id, user_id=member.id))
        db.commit()
    return {"status": "added", "user_id": member.id, "username": member.username}

@router.delete("/bots/{bot_id}/team/{user_id}")
def remove_team_member_api(
    bot_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found, or you're not the owner")
    db.query(BotCollaborator).filter(BotCollaborator.bot_id == bot_id, BotCollaborator.user_id == user_id).delete()
    db.commit()
    return {"status": "removed"}

# ========== Stats & Overview ==========
@router.get("/stats")
def get_stats_api(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    contacts_count = db.query(Contact).filter(Contact.owner_id == current_user.id).count()
    deals_count = db.query(Deal).filter(Deal.owner_id == current_user.id).count()
    messages_today = db.query(ChatHistory).filter(
        ChatHistory.user_id == current_user.id, ChatHistory.created_at >= today_start
    ).count()

    # SaleRecord breakdown
    sales_q = db.query(SaleRecord).filter(SaleRecord.owner_id == current_user.id)
    sales_today_q = sales_q.filter(SaleRecord.created_at >= today_start)

    def _count(q, dtype): return q.filter(SaleRecord.delivery_type == dtype).count()
    def _sum(q): return sum(r.grand_total for r in q.all()) or 0.0

    reservations_today = db.query(Reservation).filter(
        Reservation.owner_id == current_user.id,
        Reservation.created_at >= today_start
    ).count()

    # Appointment-bot revenue series (last 7 days, by appointment_date) — feeds the
    # Overview dashboard's revenue chart. Cancelled appointments don't count as revenue.
    # Scoped by bot_id (owned OR collaborator bots), not owner_id directly — a team
    # member added via the Team page didn't create these appointments, but should
    # still see the same numbers as the bot owner.
    visible_bot_ids = [b.id for b in _bots_visible_to(current_user, db)]
    appt_q = db.query(Appointment).filter(Appointment.bot_id.in_(visible_bot_ids))
    revenue_series = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        day_appts = appt_q.filter(Appointment.appointment_date == day_str, Appointment.status != "Cancelled").all()
        revenue_series.append({
            "date": day_str,
            "revenue": round(sum(a.consultation_fee or 0 for a in day_appts), 2),
        })
    appointments_today = appt_q.filter(Appointment.appointment_date == today.strftime("%Y-%m-%d")).count()

    return {
        "contacts": contacts_count,
        "deals": deals_count,
        "messages_today": messages_today,
        "pipeline_value": 0.0,
        "hot_leads": 0,
        # Sales counters
        "sales_today": sales_today_q.count(),
        "revenue_today": round(_sum(sales_today_q), 2),
        "sales_total": sales_q.count(),
        "revenue_total": round(_sum(sales_q), 2),
        # By delivery type (today)
        "delivery_today": _count(sales_today_q, "delivery"),
        "pickup_today": _count(sales_today_q, "pickup"),
        "dine_in_today": _count(sales_today_q, "dine_in"),
        "car_delivery_today": _count(sales_today_q, "car_delivery"),
        "reservations_today": reservations_today,
        # Appointment-bot fields (Overview dashboard)
        "appointments_today": appointments_today,
        "revenue_series": revenue_series,
    }

@router.get("/user/overview")
def get_user_overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bots = db.query(WhatsappBot).filter(WhatsappBot.owner_id == current_user.id).all()
    agents = db.query(VapiAgent).filter(VapiAgent.owner_id == current_user.id).all()
    
    return {
        "whatsapp_bots": [{"name": b.name, "status": "live"} for b in bots],
        "vapi_agents": [{"name": a.name, "status": a.status} for a in agents],
        "recent_conversations": [],
        "stats": {"total_messages": 0, "total_calls": sum(a.total_calls for a in agents)}
    }

# ========== AI Config ==========
@router.get("/settings/my-config")
def get_my_config(current_user: User = Depends(get_current_user)):
    return {
        "ai_provider": current_user.ai_provider or "groq",
        "groq_api_key": mask_sensitive(current_user.groq_api_key),
        "gemini_api_key": mask_sensitive(current_user.gemini_api_key),
        "openai_api_key": mask_sensitive(current_user.openai_api_key),
        "minimax_api_key": mask_sensitive(current_user.minimax_api_key),
        "anthropic_api_key": mask_sensitive(current_user.anthropic_api_key),
        "openrouter_api_key": mask_sensitive(current_user.openrouter_api_key),
        "openrouter_model": current_user.openrouter_model or "nousresearch/hermes-3-llama-3.1-405b:free",
        "default_voice": current_user.default_voice or "Alloy",
        "default_first_message": current_user.default_first_message or "Hello!"
    }

@router.post("/settings/save-config")
def save_config(config: UserConfigSave, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.ai_provider = config.ai_provider
    current_user.groq_api_key = config.groq_api_key
    current_user.gemini_api_key = config.gemini_api_key
    current_user.openai_api_key = config.openai_api_key
    current_user.minimax_api_key = config.minimax_api_key
    current_user.anthropic_api_key = config.anthropic_api_key
    current_user.openrouter_api_key = config.openrouter_api_key
    current_user.openrouter_model = config.openrouter_model or "nousresearch/hermes-3-llama-3.1-405b:free"
    current_user.default_voice = config.default_voice
    current_user.default_first_message = config.default_first_message
    db.commit()
    return {"message": "Saved"}

# ========== Admin Endpoints ==========
@router.get("/admin/users")
def admin_list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "role": u.role, "is_suspended": u.is_suspended} for u in users]

@router.post("/admin/suspend-user")
def admin_suspend_user(data: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.get("username")).first()
    if not user: raise HTTPException(404, "Not found")
    user.is_suspended = data.get("suspended", True)
    db.commit()
    log_audit(db, admin.id, "SUSPEND_USER", f"Suspended user: {user.username}" if user.is_suspended else f"Unsuspended user: {user.username}")
    return {"status": "updated"}

# ========== Bug #5: Admin Settings Persistence ==========
@router.get("/admin/settings")
def get_admin_settings(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    settings = db.query(AdminSetting).all()
    return {s.key: s.value for s in settings}

@router.post("/admin/settings")
def update_admin_settings(data: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    for key, value in data.items():
        setting = db.query(AdminSetting).filter(AdminSetting.key == key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = AdminSetting(key=key, value=str(value))
            db.add(setting)
    db.commit()
    log_audit(db, admin.id, "UPDATE_ADMIN_SETTINGS", f"Updated keys: {', '.join(data.keys())}")
    return {"status": "success"}

# ========== Bug #7: Bot Status Monitoring ==========
@router.get("/admin/bot-status")
def get_bot_status_dashboard(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bots = db.query(WhatsappBot).all()
    return [{
        "id": b.id, "name": b.name, "owner": b.owner.username if b.owner else "Unknown",
        "status": b.status, "last_health_check": b.last_health_check.isoformat() if b.last_health_check else None
    } for b in bots]

# ========== Bug #10: Activity Logs ==========
@router.get("/admin/audit-logs")
def get_audit_logs(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return [{
        "id": l.id, "user": l.user.username if l.user else "System",
        "action": l.action, "details": l.details, "created_at": l.created_at.isoformat()
    } for l in logs]

# ========== Seed Demo Bots ==========
@router.post("/admin/seed-demo-bots")
def seed_demo_bots(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """One-click seed all 7 demo restaurant bots. Safe to call multiple times (skips existing)."""
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from populate_demo_bots import BOTS, make_config, MANAGER_NUMBER
    created, skipped = [], []
    for b in BOTS:
        existing = db.query(WhatsappBot).filter(WhatsappBot.name == b["name"]).first()
        if existing:
            skipped.append(b["name"])
            continue
        new_bot = WhatsappBot(
            owner_id=admin.id,
            name=b["name"],
            business_name=b["business_name"],
            bot_type=b.get("bot_type", "restaurant"),
            meta_token="", phone_number_id="", waba_id="", verify_token="",
            manager_number=MANAGER_NUMBER,
            ai_provider="groq", ai_api_key="",
            language="en",
            system_prompt=b.get("system_prompt", ""),
            tax_rate=b.get("tax_rate", 0.08),
            delivery_fee=b.get("delivery_fee", 3.0),
            config_json=b["config"],
            status="pending_config",
        )
        db.add(new_bot)
        db.flush()
        if b["name"] not in (admin.bots or []):
            admin.bots = (admin.bots or []) + [b["name"]]
        created.append(b["name"])
    db.commit()
    log_audit(db, admin.id, "SEED_DEMO_BOTS", f"Created {len(created)}, skipped {len(skipped)}")
    return {"created": created, "skipped": skipped, "message": f"✅ {len(created)} bots created, {len(skipped)} already existed"}

# ========== AI Chat ==========
@router.post("/ai/chat")
async def ai_chat(req: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_msg = req.messages[-1]["content"] if req.messages else ""
    provider = current_user.ai_provider or "groq"
    api_key = ""
    
    if provider == "groq": api_key = current_user.groq_api_key or os.getenv("GROQ_API_KEY")
    elif provider == "gemini": api_key = current_user.gemini_api_key or os.getenv("GEMINI_API_KEY")
    elif provider == "openai": api_key = current_user.openai_api_key or os.getenv("OPENAI_API_KEY")
    elif provider == "minimax": api_key = current_user.minimax_api_key or os.getenv("MINIMAX_API_KEY")
    elif provider == "anthropic": api_key = current_user.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    elif provider == "openrouter": api_key = current_user.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return {"reply": "⚠️ AI API Key is missing. Please go to Settings and add your API key."}

    try:
        from ai_utils import (
            call_groq_api, call_gemini_api, call_openai_api, call_anthropic_api, call_openrouter_api
        )
        messages = [
            {"role": "system", "content": f"You are a helpful CRM assistant for {current_user.username}. Help with managing bots, contacts, and business operations."},
        ] + req.messages
        if provider == "groq":
            reply = await call_groq_api(messages, api_key)
        elif provider == "gemini":
            reply = await call_gemini_api(user_msg, messages, api_key)
        elif provider == "openai":
            reply = await call_openai_api(messages, api_key)
        elif provider == "anthropic":
            reply = await call_anthropic_api(messages, api_key)
        elif provider == "openrouter":
            or_model = current_user.openrouter_model or "nousresearch/hermes-3-llama-3.1-405b:free"
            reply = await call_openrouter_api(messages, api_key, model=or_model)
        else:
            reply = await call_groq_api(messages, api_key)
        return {"reply": reply}
    except Exception as e:
        logger.error(f"AI Chat Error: {e}")
        return {"reply": f"Sorry, I couldn't process that. Error: {str(e)}"}

# ========== Test Endpoints ==========
@router.post("/test/manager-ping")
async def test_manager_ping(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a plain-text test message to MANAGER_NUMBER. Returns raw WhatsApp API response."""
    import aiohttp as _aiohttp
    from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, MANAGER_NUMBER, WHATSAPP_API_VERSION
    from session import SharedSession

    to = MANAGER_NUMBER.lstrip("+") if MANAGER_NUMBER else ""
    if not to:
        return {"ok": False, "error": "MANAGER_NUMBER env var not set"}

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": "🔔 Wild CRM — test manager notification. If you see this, notifications are working!"}
    }
    try:
        session = await SharedSession.get_session()
        async with session.post(url, json=payload, headers=headers) as r:
            body = await r.json()
            note = "API accepted. If message not received: manager must first send any WhatsApp message TO the bot number to open the 24hr conversation window." if r.status < 400 else ""
            return {"ok": r.status < 400, "status": r.status, "response": body, "to": to, "phone_id": WHATSAPP_PHONE_NUMBER_ID, "note": note}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ========== Plugin System ==========
@router.get("/plugins")
def list_available_plugins(current_user: User = Depends(get_current_user)):
    from plugins import list_plugins
    return list_plugins()

@router.get("/bots/whatsapp/{bot_id}/plugins")
def get_bot_plugins(bot_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    rows = db.query(BotPlugin).filter(BotPlugin.bot_id == bot_id).all()
    return [{"plugin_name": r.plugin_name, "enabled": r.enabled, "config": json.loads(r.config_json or "{}")} for r in rows]

class PluginSave(BaseModel):
    enabled: bool = True
    config: dict = {}

@router.post("/bots/whatsapp/{bot_id}/plugins/{plugin_name}")
def save_bot_plugin(bot_id: int, plugin_name: str, data: PluginSave,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    row = db.query(BotPlugin).filter(BotPlugin.bot_id == bot_id, BotPlugin.plugin_name == plugin_name).first()
    if row:
        row.enabled = data.enabled
        row.config_json = json.dumps(data.config)
    else:
        row = BotPlugin(bot_id=bot_id, plugin_name=plugin_name, enabled=data.enabled, config_json=json.dumps(data.config))
        db.add(row)
    db.commit()
    return {"ok": True, "plugin_name": plugin_name, "enabled": data.enabled}

@router.delete("/bots/whatsapp/{bot_id}/plugins/{plugin_name}")
def delete_bot_plugin(bot_id: int, plugin_name: str,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = db.query(WhatsappBot).filter(WhatsappBot.id == bot_id, WhatsappBot.owner_id == current_user.id).first()
    if not bot:
        raise HTTPException(404, "Bot not found")
    db.query(BotPlugin).filter(BotPlugin.bot_id == bot_id, BotPlugin.plugin_name == plugin_name).delete()
    db.commit()
    return {"ok": True}

# ========== Reservations & Orders ==========
@router.get("/reservations")
def get_reservations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Reservation).filter(
        Reservation.owner_id == current_user.id
    ).order_by(Reservation.created_at.desc()).limit(200).all()
    return [{
        "id": r.id,
        "customer_name": r.customer_name,
        "customer_phone": r.customer_phone,
        "party_size": r.party_size,
        "reservation_date": r.reservation_date,
        "reservation_time": r.reservation_time,
        "status": r.status,
        "notes": r.notes,
        "bot_id": r.bot_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]

@router.patch("/reservations/{res_id}")
def update_reservation_status(res_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(Reservation).filter(Reservation.id == res_id, Reservation.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(404, "Not found")
    if "status" in data:
        r.status = data["status"]
    if "notes" in data:
        r.notes = data["notes"]
    db.commit()
    return {"status": "updated"}

@router.get("/sales")
def get_sales(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SaleRecord).filter(
        SaleRecord.owner_id == current_user.id
    ).order_by(SaleRecord.created_at.desc()).limit(200).all()
    return [{
        "id": r.id,
        "order_id": r.order_id,
        "customer_phone": r.customer_phone,
        "delivery_type": r.delivery_type,
        "subtotal": r.subtotal,
        "tax": r.tax,
        "delivery_fee": r.delivery_fee,
        "grand_total": r.grand_total,
        "payment_method": r.payment_method,
        "car_number": r.car_number,
        "bot_id": r.bot_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
