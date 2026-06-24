# database.py - SaaS Hardened Version
import os
import json
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey, Boolean, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from typing import Optional, List
import secrets
from utils import get_order_total, get_delivery_fee

# ========== Database Setup ==========
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip() or "sqlite:///./platform.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ========== Password & JWT ==========
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "wild-automation-crm-stable-secret-key-change-it")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

# ========== Database Dependency ==========
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ========== Models ==========

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")
    bots_json = Column(Text, default="[]")
    is_suspended = Column(Boolean, default=False)
    assigned_bots = Column(Text, default="[]")
    assigned_vapi_agents = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # AI Config
    ai_provider = Column(String, default="groq")
    ai_api_key = Column(String, default="")
    groq_api_key = Column(String, default="")
    gemini_api_key = Column(String, default="")
    openai_api_key = Column(String, default="")
    minimax_api_key = Column(String, default="")
    anthropic_api_key = Column(String, default="")
    openrouter_api_key = Column(String, default="")
    openrouter_model = Column(String, default="nousresearch/hermes-3-llama-3.1-405b:free")
    default_voice = Column(String, default="Alloy")
    default_first_message = Column(String, default="Hello, how can I help you?")

    contacts = relationship("Contact", back_populates="owner", cascade="all, delete-orphan")
    deals = relationship("Deal", back_populates="owner", cascade="all, delete-orphan")
    calls = relationship("Call", back_populates="owner", cascade="all, delete-orphan")
    vapi_agents = relationship("VapiAgent", back_populates="owner", cascade="all, delete-orphan")
    whatsapp_bots = relationship("WhatsappBot", back_populates="owner", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")
    config_audits = relationship("BotConfigAudit", back_populates="user", cascade="all, delete-orphan")

    @property
    def bots(self) -> List[str]:
        return json.loads(self.bots_json or "[]")

    @bots.setter
    def bots(self, value: List[str]):
        self.bots_json = json.dumps(value)

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    first_name = Column(String, default="")
    last_name = Column(String, default="")
    company = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    status = Column(String, default="New")
    source = Column(String, default="Manual")
    notes = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="contacts")

class Deal(Base):
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, default="New Deal")
    company = Column(String, default="")
    contact_name = Column(String, default="")
    value = Column(Float, default=0.0)
    stage = Column(String, default="Discovery")
    probability = Column(Integer, default=20)
    expected_close = Column(DateTime, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="deals")

class Call(Base):
    __tablename__ = "calls"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contact_name = Column(String, default="Unknown")
    phone = Column(String, default="")
    direction = Column(String, default="Inbound")
    duration_minutes = Column(Float, default=0.0)
    outcome = Column(String, default="Resolved")
    agent = Column(String, default="")
    notes = Column(Text, default="")
    call_date = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="calls")

class VapiAgent(Base):
    __tablename__ = "vapi_agents"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    vapi_api_key = Column(String, default="")
    vapi_agent_id = Column(String, default="")
    phone_number_id = Column(String, default="")
    first_message = Column(Text, default="")
    system_prompt = Column(Text, default="")
    voice = Column(String, default="Alloy")
    crm_sync = Column(Boolean, default=False)
    webhook_url = Column(String, default="")
    status = Column(String, default="Draft")
    total_calls = Column(Integer, default=0)
    conversion_rate = Column(Float, default=0.0)
    last_call = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="vapi_agents")

class WhatsappBot(Base):
    __tablename__ = "whatsapp_bots"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, unique=True, index=True, nullable=False)
    bot_type = Column(String, default="restaurant")
    business_niche = Column(String, default="general")
    meta_token = Column(String, default="")
    phone_number_id = Column(String, default="")
    waba_id = Column(String, default="")
    verify_token = Column(String, default="")
    ai_provider = Column(String, default="groq")
    ai_api_key = Column(String, default="")
    manager_number = Column(String, default="")
    language = Column(String, default="en")
    business_name = Column(String, default="")
    system_prompt = Column(Text, default="")
    webhook_url = Column(String, default="")
    tax_rate = Column(Float, default=0.08)
    delivery_fee = Column(Float, default=0.0)
    config_json = Column(Text, default="{}")
    vapi_agent_id = Column(String, default="")
    forwarding_url = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="whatsapp_bots")
    
    # Cascade Protection (Bug #6)
    session_states = relationship("SessionState", back_populates="bot", cascade="all, delete-orphan")
    config_audits = relationship("BotConfigAudit", back_populates="bot", cascade="all, delete-orphan")
    reservations = relationship("Reservation", back_populates="bot", cascade="all, delete-orphan")
    event_logs = relationship("BotEventLog", back_populates="bot", cascade="all, delete-orphan")
    status = Column(String, default="active") # Bug #7: monitoring status
    last_health_check = Column(DateTime, nullable=True)

    # ── Dual-provider fields ──────────────────────────────────────────────────
    # provider: "meta" (default, Meta Cloud API) | "wwebjs" (own number via QR)
    provider          = Column(String, default="meta")
    # wwebjs_session: session name in wa-bridge, e.g. "bot_7"
    wwebjs_session    = Column(String, nullable=True)
    # wwebjs_bridge_url: URL of the wa-bridge service for this bot.
    # If blank, falls back to WWEBJS_BRIDGE_URL env var.
    wwebjs_bridge_url = Column(String, nullable=True)

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String)
    payload_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class SessionState(Base):
    __tablename__ = "session_states"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=True)
    sender_number = Column(String, index=True, nullable=False)
    state_json = Column(Text, default="{}")
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    bot = relationship("WhatsappBot", back_populates="session_states")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_number = Column(String, index=True)
    items_json = Column(Text, default="[]")
    total_amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    delivery_amount = Column(Float, default=0.0)
    grand_total = Column(Float, default=0.0)
    delivery_type = Column(String, default="pickup")
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)

# ========== SaaS Audit & Settings Models (Bugs #2, #5, #10) ==========

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    action = Column(String)
    details = Column(Text)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="audit_logs")

class BotConfigAudit(Base):
    __tablename__ = "bot_config_audits"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    field = Column(String)
    old_value = Column(Text)
    new_value = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    bot = relationship("WhatsappBot", back_populates="config_audits")
    user = relationship("User", back_populates="config_audits")

class AdminSetting(Base):
    __tablename__ = "admin_settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(Text)
    description = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_phone = Column(String, default="", index=True)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=True)
    customer_phone = Column(String, index=True, default="")
    customer_name = Column(String, default="")
    party_size = Column(Integer, default=2)
    reservation_date = Column(String, default="")
    reservation_time = Column(String, default="")
    status = Column(String, default="Pending")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    bot = relationship("WhatsappBot", back_populates="reservations")

class Appointment(Base):
    """One row per booked/cancelled/rescheduled appointment for the appointment bot."""
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=True, index=True)
    customer_phone = Column(String, index=True, default="")
    customer_name = Column(String, default="")
    service = Column(String, default="")
    department = Column(String, default="")   # e.g. "dental" | "aesthetic"
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True, index=True)
    procedure_id = Column(Integer, ForeignKey("procedures.id", ondelete="SET NULL"), nullable=True, index=True)
    consultation_fee = Column(Float, default=0.0)
    appointment_date = Column(String, default="")   # normalized YYYY-MM-DD (falls back to free text if unparsable)
    appointment_time = Column(String, default="")    # normalized HH:MM 24h (falls back to free text if unparsable)
    status = Column(String, default="Confirmed", index=True)  # Confirmed | Cancelled | Rescheduled | Completed
    notes = Column(Text, default="")
    reminder_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Doctor(Base):
    """A doctor/specialist offered by a clinic bot, scoped to one department."""
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=False, index=True)
    department = Column(String, nullable=False, index=True)  # "dental" | "aesthetic"
    name = Column(String, nullable=False)
    gender = Column(String, default="")           # "male" | "female" | "" (unspecified)
    bio = Column(Text, default="")               # short description of specialty/experience
    consultation_fee = Column(Float, default=0.0)
    other_fees_json = Column(Text, default="{}")  # e.g. {"X-Ray": 20, "Cleaning": 50}
    shift_json = Column(Text, default="{}")        # e.g. {"mon": "10:00-18:00", "tue": "off", ...}
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Procedure(Base):
    """A bookable procedure/treatment within a department (e.g. 'Teeth Whitening', 'Botox')."""
    __tablename__ = "procedures"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=False, index=True)
    department = Column(String, nullable=False, index=True)  # "dental" | "aesthetic"
    name = Column(String, nullable=False)
    sessions_required = Column(Integer, default=1)
    fee_per_session = Column(Float, default=0.0)
    description = Column(Text, default="")
    upsell_with_json = Column(Text, default="[]")  # list of other procedure names in same department
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class LabReport(Base):
    """Audit trail of lab reports uploaded by patients + the AI's doctor recommendation."""
    __tablename__ = "lab_reports"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_phone = Column(String, index=True, default="")
    filename = Column(String, default="")
    extracted_text_excerpt = Column(Text, default="")
    department_recommended = Column(String, default="")
    doctor_recommended_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    ai_summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class KnowledgeDocument(Base):
    """Source documents ingested into the per-bot RAG knowledge base (ai/rag.py)."""
    __tablename__ = "knowledge_documents"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, default="")
    source_type = Column(String, default="text")  # text | pdf | url
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class BotEventLog(Base):
    __tablename__ = "bot_event_logs"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    details = Column(Text, default="")
    customer_phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    bot = relationship("WhatsappBot", back_populates="event_logs")

class SaleRecord(Base):
    """One row per confirmed WhatsApp order. Created by restaurant flow on order confirm."""
    __tablename__ = "sale_records"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(Integer, nullable=False, index=True)
    customer_phone = Column(String, default="", index=True)
    delivery_type = Column(String, default="pickup", index=True)  # pickup|delivery|dine_in|car_delivery
    order_id = Column(String, default="")
    subtotal = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    delivery_fee = Column(Float, default=0.0)
    grand_total = Column(Float, default=0.0)
    payment_method = Column(String, default="")
    car_number = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class BotPlugin(Base):
    __tablename__ = "bot_plugins"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("whatsapp_bots.id", ondelete="CASCADE"), nullable=False, index=True)
    plugin_name = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    config_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    phone = Column(String, index=True, nullable=False)
    name = Column(String, default="")
    lang = Column(String, default="en")
    address = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

# ========== CRUD Helpers ==========

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()

def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if user and verify_password(password, user.hashed_password):
        return user
    return None

def create_user(db: Session, username: str, password: str, role: str = "user") -> Optional[User]:
    if get_user_by_username(db, username):
        return None
    new_user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def get_contacts(db: Session, owner_id: int):
    return db.query(Contact).filter(Contact.owner_id == owner_id).all()

def create_contact(db: Session, owner_id: int, data: dict):
    new_contact = Contact(owner_id=owner_id, **data)
    db.add(new_contact)
    db.commit()
    db.refresh(new_contact)
    return new_contact

def get_deals(db: Session, owner_id: int):
    return db.query(Deal).filter(Deal.owner_id == owner_id).all()

def create_deal(db: Session, owner_id: int, data: dict):
    new_deal = Deal(owner_id=owner_id, **data)
    db.add(new_deal)
    db.commit()
    db.refresh(new_deal)
    return new_deal

def get_calls(db: Session, owner_id: int):
    return db.query(Call).filter(Call.owner_id == owner_id).all()

def create_call(db: Session, owner_id: int, data: dict):
    new_call = Call(owner_id=owner_id, **data)
    db.add(new_call)
    db.commit()
    db.refresh(new_call)
    return new_call

def get_whatsapp_bots(db: Session, owner_id: int):
    return db.query(WhatsappBot).filter(WhatsappBot.owner_id == owner_id).all()

def save_new_order(db: Session, owner_id: int, customer_phone: str, session_data: dict, bot: WhatsappBot):
    order_items = session_data.get("order", {})
    total = get_order_total(order_items)
    tax_rate = bot.tax_rate if bot else 0.08
    tax_amount = total * tax_rate
    delivery_charge = get_delivery_fee(total, session_data.get("delivery_type"))
    grand_total = total + tax_amount + delivery_charge
    
    new_order = Order(
        owner_id=owner_id,
        customer_number=customer_phone,
        items_json=json.dumps(order_items),
        total_amount=total,
        tax_amount=tax_amount,
        delivery_amount=delivery_charge,
        grand_total=grand_total,
        delivery_type=session_data.get("delivery_type", "pickup"),
        status="Pending"
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    if bot:
        log_bot_event(bot.id, "ORDER_CREATED",
                      f"Order #{new_order.id} | ${grand_total:.2f} | {session_data.get('delivery_type','?')} | {len(order_items)} item(s)",
                      customer_phone=customer_phone)
    return new_order

def get_session_data(db: Session, bot_id: int, phone: str):
    state = db.query(SessionState).filter(SessionState.bot_id == bot_id, SessionState.sender_number == phone).first()
    return json.loads(state.state_json) if state else {}

# ========== Appointment CRUD ==========

def create_appointment(db: Session, owner_id: int, bot_id: int, customer_phone: str,
                        service: str, appointment_date: str, appointment_time: str,
                        customer_name: str = "", notes: str = "", department: str = "",
                        doctor_id: int = None, consultation_fee: float = 0.0,
                        procedure_id: int = None) -> "Appointment":
    appt = Appointment(
        owner_id=owner_id, bot_id=bot_id, customer_phone=customer_phone,
        customer_name=customer_name, service=service, department=department,
        doctor_id=doctor_id, consultation_fee=consultation_fee, procedure_id=procedure_id,
        appointment_date=appointment_date, appointment_time=appointment_time,
        status="Confirmed", notes=notes,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    log_bot_event(bot_id, "APPOINTMENT_CREATED",
                  f"#{appt.id} | {service} | {appointment_date} {appointment_time}",
                  customer_phone=customer_phone)
    return appt

# ========== Doctor CRUD ==========

def create_doctor(db: Session, bot_id: int, department: str, name: str, bio: str = "",
                   consultation_fee: float = 0.0, other_fees: dict = None, shifts: dict = None,
                   gender: str = "") -> "Doctor":
    doc = Doctor(
        bot_id=bot_id, department=department, name=name, bio=bio, gender=gender,
        consultation_fee=consultation_fee,
        other_fees_json=json.dumps(other_fees or {}),
        shift_json=json.dumps(shifts or {}),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc

def get_doctors_by_bot(db: Session, bot_id: int, active_only: bool = True):
    q = db.query(Doctor).filter(Doctor.bot_id == bot_id)
    if active_only:
        q = q.filter(Doctor.active == True)
    return q.order_by(Doctor.department, Doctor.name).all()

def get_doctors_by_department(db: Session, bot_id: int, department: str, active_only: bool = True):
    q = db.query(Doctor).filter(Doctor.bot_id == bot_id, Doctor.department == department)
    if active_only:
        q = q.filter(Doctor.active == True)
    return q.order_by(Doctor.name).all()

def get_doctor_by_id(db: Session, bot_id: int, doctor_id: int):
    return db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.bot_id == bot_id).first()

def update_doctor(db: Session, doctor: "Doctor", data: dict) -> "Doctor":
    for key in ("department", "name", "gender", "bio", "consultation_fee", "active"):
        if key in data:
            setattr(doctor, key, data[key])
    if "other_fees" in data:
        doctor.other_fees_json = json.dumps(data["other_fees"] or {})
    if "shifts" in data:
        doctor.shift_json = json.dumps(data["shifts"] or {})
    db.commit()
    db.refresh(doctor)
    return doctor

def delete_doctor(db: Session, doctor: "Doctor"):
    db.delete(doctor)
    db.commit()

def get_enabled_departments_for_bot(db: Session, bot_id: int) -> list:
    """A department is 'enabled' for a bot if it has at least one active doctor configured."""
    rows = db.query(Doctor.department).filter(Doctor.bot_id == bot_id, Doctor.active == True).distinct().all()
    return [r[0] for r in rows]

# ========== Procedure CRUD ==========

def create_procedure(db: Session, bot_id: int, department: str, name: str,
                      sessions_required: int = 1, fee_per_session: float = 0.0,
                      description: str = "", upsell_with: list = None) -> "Procedure":
    proc = Procedure(
        bot_id=bot_id, department=department, name=name,
        sessions_required=sessions_required, fee_per_session=fee_per_session,
        description=description, upsell_with_json=json.dumps(upsell_with or []),
    )
    db.add(proc)
    db.commit()
    db.refresh(proc)
    return proc

def get_procedures_by_bot(db: Session, bot_id: int, active_only: bool = True):
    q = db.query(Procedure).filter(Procedure.bot_id == bot_id)
    if active_only:
        q = q.filter(Procedure.active == True)
    return q.order_by(Procedure.department, Procedure.name).all()

def get_procedures_by_department(db: Session, bot_id: int, department: str, active_only: bool = True):
    q = db.query(Procedure).filter(Procedure.bot_id == bot_id, Procedure.department == department)
    if active_only:
        q = q.filter(Procedure.active == True)
    return q.order_by(Procedure.name).all()

def get_procedure_by_id(db: Session, bot_id: int, procedure_id: int):
    return db.query(Procedure).filter(Procedure.id == procedure_id, Procedure.bot_id == bot_id).first()

def update_procedure(db: Session, procedure: "Procedure", data: dict) -> "Procedure":
    for key in ("department", "name", "sessions_required", "fee_per_session", "description", "active"):
        if key in data:
            setattr(procedure, key, data[key])
    if "upsell_with" in data:
        procedure.upsell_with_json = json.dumps(data["upsell_with"] or [])
    db.commit()
    db.refresh(procedure)
    return procedure

def delete_procedure(db: Session, procedure: "Procedure"):
    db.delete(procedure)
    db.commit()

# ========== Slot Availability ==========

def get_doctor_appointments_on_date(db: Session, bot_id: int, doctor_id: int, appointment_date: str):
    """All active (Confirmed/Rescheduled) appointments for a doctor on a given normalized YYYY-MM-DD date."""
    return (
        db.query(Appointment)
        .filter(
            Appointment.bot_id == bot_id,
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status.in_(["Confirmed", "Rescheduled"]),
        )
        .all()
    )

# ========== Lab Report CRUD ==========

def create_lab_report(db: Session, bot_id: int, customer_phone: str, filename: str,
                       extracted_text_excerpt: str, department_recommended: str = "",
                       doctor_recommended_id: int = None, ai_summary: str = "") -> "LabReport":
    report = LabReport(
        bot_id=bot_id, customer_phone=customer_phone, filename=filename,
        extracted_text_excerpt=extracted_text_excerpt[:2000],
        department_recommended=department_recommended,
        doctor_recommended_id=doctor_recommended_id, ai_summary=ai_summary,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report

def get_upcoming_appointments(db: Session, bot_id: int, customer_phone: str):
    return (
        db.query(Appointment)
        .filter(
            Appointment.bot_id == bot_id,
            Appointment.customer_phone == customer_phone,
            Appointment.status.in_(["Confirmed", "Rescheduled"]),
        )
        .order_by(Appointment.created_at.desc())
        .all()
    )

def get_appointment_by_id(db: Session, bot_id: int, customer_phone: str, appointment_id: int):
    return (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment_id,
            Appointment.bot_id == bot_id,
            Appointment.customer_phone == customer_phone,
        )
        .first()
    )

def cancel_appointment(db: Session, appointment: "Appointment"):
    appointment.status = "Cancelled"
    db.commit()
    log_bot_event(appointment.bot_id, "APPOINTMENT_CANCELLED", f"#{appointment.id}",
                  customer_phone=appointment.customer_phone)
    return appointment

def reschedule_appointment(db: Session, appointment: "Appointment", new_date: str, new_time: str):
    appointment.appointment_date = new_date
    appointment.appointment_time = new_time
    appointment.status = "Rescheduled"
    db.commit()
    log_bot_event(appointment.bot_id, "APPOINTMENT_RESCHEDULED",
                  f"#{appointment.id} -> {new_date} {new_time}",
                  customer_phone=appointment.customer_phone)
    return appointment

# ========== Knowledge Base CRUD ==========

def add_knowledge_document(db: Session, bot_id: int, title: str, source_type: str, chunk_count: int) -> "KnowledgeDocument":
    doc = KnowledgeDocument(bot_id=bot_id, title=title, source_type=source_type, chunk_count=chunk_count)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc

def get_knowledge_documents(db: Session, bot_id: int):
    return db.query(KnowledgeDocument).filter(KnowledgeDocument.bot_id == bot_id).all()

def save_session_data(db: Session, bot_id: int, phone: str, data: dict):
    state = db.query(SessionState).filter(SessionState.bot_id == bot_id, SessionState.sender_number == phone).first()
    if state:
        state.state_json = json.dumps(data)
    else:
        state = SessionState(bot_id=bot_id, sender_number=phone, state_json=json.dumps(data))
        db.add(state)
    db.commit()

# ========== Dummy Data & Migration ==========
def populate_dummy_data(db: Session):
    if not get_user_by_username(db, "admin"):
        create_user(db, "admin", os.getenv("ADMIN_PASSWORD", "admin123"), role="admin")
    if not get_user_by_username(db, "user1"):
        create_user(db, "user1", "user123", role="user")

def load_customer_profiles_from_db():
    # Placeholder for profiles cache if needed
    pass

def log_bot_event(bot_id: int, event_type: str, details: str = "", customer_phone: str = None):
    """Fire-and-forget bot event logger. Uses its own session so caller's session isn't affected."""
    if not bot_id:
        return
    try:
        db = SessionLocal()
        entry = BotEventLog(bot_id=bot_id, event_type=event_type,
                            details=details[:1000], customer_phone=customer_phone)
        db.add(entry)
        db.commit()
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass

def migrate_db():
    try:
        Base.metadata.create_all(bind=engine)
        # Add new columns to existing tables without dropping them
        with engine.connect() as conn:
            inspector = inspect(engine)
            for table_name, columns in [
                ("orders", ["delivery_type TEXT DEFAULT 'pickup'"]),
                ("whatsapp_bots", [
                    "provider TEXT DEFAULT 'meta'",
                    "wwebjs_session TEXT",
                    "wwebjs_bridge_url TEXT",
                ]),
            ]:
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)} if table_name in inspector.get_table_names() else set()
                for col_def in columns:
                    col_name = col_def.split()[0]
                    if col_name not in existing_cols:
                        try:
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_def}"))
                            conn.commit()
                        except Exception:
                            pass
        print("Database Migrated Successfully.")
    except Exception as e:
        print(f"[DB] Warning: migrate_db failed: {e}. App will start but DB operations may fail until connection is restored.")
