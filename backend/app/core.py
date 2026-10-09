import os, re, secrets, hashlib
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, String, Integer, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# Railway must never inherit the local SQLite / embedded-worker defaults.
if os.environ.get('RAILWAY_ENVIRONMENT_ID'):
    os.environ.setdefault('APP_ENVIRONMENT', 'production')
    os.environ.setdefault('LOCAL_WORKER', 'false')
    os.environ.setdefault('DEPLOYMENT_SEND_LOCK', 'true')
    os.environ.setdefault('BULK_DISPATCH_ENABLED', 'false')

MIN_PASSWORD_LENGTH = 7

class Settings(BaseSettings):
    database_url: str = "sqlite:///./hys-local.db"
    redis_url: str = "redis://localhost:6379/0"
    dry_run: bool = True
    local_worker: bool = True
    app_environment: str = 'local'
    panel_origin: str = ''
    panel_proxy_secret: str = ''
    bulk_media_dir: str = ''
    bulk_dispatch_enabled: bool = True
    deployment_send_lock: bool = False
    meta_access_token: str = ""
    meta_phone_number_id: str = ""
    meta_waba_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    meta_graph_api_version: str = "v25.0"
    webhook_public_url: str = ""
    webhook_production_enabled: bool = False
    webhook_production_phone_number_id: str = ""
    webhook_production_waba_id: str = ""
    meta_environment: str = "test"
    live_send_enabled: bool = False
    bulk_daily_limit: int = 10000
    meta_test_message_enabled: bool = False
    meta_test_phone_number_id: str = ''
    meta_test_waba_id: str = ''
    meta_production_phone_number_ids: str = ''
    meta_test_recipients: str = ''
    bootstrap_token: str = ""
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2]/'.env', extra="ignore", env_ignore_empty=True)
settings = Settings()
def database_dsn(value):
    if value.startswith('postgres://'):return value.replace('postgres://','postgresql+psycopg://',1)
    if value.startswith('postgresql://'):return value.replace('postgresql://','postgresql+psycopg://',1)
    return value
settings.database_url=database_dsn(settings.database_url)
def database_engine_options(url):
    if url.startswith('sqlite'):
        return {'connect_args': {'check_same_thread': False}}
    if url.startswith('postgresql+psycopg://'):
        return {'connect_args': {'connect_timeout': 5}, 'pool_timeout': 5}
    return {}

engine = create_engine(settings.database_url, pool_pre_ping=True,hide_parameters=True, **database_engine_options(settings.database_url))
if settings.database_url.startswith('sqlite'):
    from sqlalchemy import event
    @event.listens_for(engine,'connect')
    def sqlite_integrity(connection,record):connection.execute('PRAGMA foreign_keys=ON')
Session = sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def today_start():return datetime.now(ZoneInfo('Europe/Istanbul')).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
def phone(value):
    n = re.sub(r"[\s()\-]", "", str(value))
    if n.startswith("00"): n = "+" + n[2:]
    if re.fullmatch(r"0[1-9]\d{9}", n): n = "+90" + n[1:]
    elif re.fullmatch(r"[1-9]\d{9}", n): n = "+90" + n
    elif re.fullmatch(r"90[1-9]\d{9}", n): n = "+" + n
    if not re.fullmatch(r"\+[1-9]\d{7,14}", n): raise ValueError("Geçersiz telefon numarası")
    return n
def mask(n): return n[:3] + "•" * max(0,len(n)-7) + n[-4:]
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="operator")
class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires: Mapped[datetime] = mapped_column(DateTime)
class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    city: Mapped[str] = mapped_column(String(100), default="")
class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("kind", "phone"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(20), index=True)
    city: Mapped[str] = mapped_column(String(100), default="")
    store: Mapped[str] = mapped_column(String(160), default="")
    group: Mapped[str] = mapped_column(String(100), default="")
    department: Mapped[str] = mapped_column(String(100), default="")
    job: Mapped[str] = mapped_column(String(100), default="")
    last_purchase: Mapped[str] = mapped_column(String(30), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    preference: Mapped[str] = mapped_column(String(30), default="whatsapp")
    consent: Mapped[str] = mapped_column(String(30), default="unverified")
    scope: Mapped[str] = mapped_column(String(50), default="")
    source: Mapped[str] = mapped_column(String(200), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    consent_date: Mapped[str] = mapped_column(String(40), default="")
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    iys_status: Mapped[str] = mapped_column(String(40), default="not_checked")
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    language: Mapped[str] = mapped_column(String(20), default="tr")
    category: Mapped[str] = mapped_column(String(30), default="MARKETING")
    status: Mapped[str] = mapped_column(String(30), default="LOCAL_DRAFT")
    body: Mapped[str] = mapped_column(Text)
    components: Mapped[str] = mapped_column(Text, default="[]")
    meta_id: Mapped[str] = mapped_column(String(100), default="")
class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    filters: Mapped[str] = mapped_column(Text, default="{}")
    variables: Mapped[str] = mapped_column(Text, default="{}")
    scheduled: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    max_count: Mapped[int] = mapped_column(Integer, default=1000)
    budget: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    first_approval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    second_approval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("campaign_id", "contact_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    phone: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(10), default="out")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    meta_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[datetime] = mapped_column(DateTime, default=now)
    unread: Mapped[bool] = mapped_column(Boolean, default=False)
    review: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
class WebhookItem(Base):
    __tablename__ = 'webhook_items'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    phone_number_id: Mapped[str] = mapped_column(String(40))
    meta_id: Mapped[str] = mapped_column(String(200), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
class SystemValue(Base):
    __tablename__ = "system_values"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
class TestMessage(Base):
    __test__ = False
    __tablename__ = 'test_messages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    recipient: Mapped[str] = mapped_column(String(20))
    phone_number_id: Mapped[str] = mapped_column(String(40))
    confirmation_hash: Mapped[str] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))
    expires: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), default='prepared')
    delivery_status: Mapped[str] = mapped_column(String(30), default='unknown')
    meta_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    api_response: Mapped[str] = mapped_column(Text, default='{}')
    error_code: Mapped[str] = mapped_column(String(30), default='')
    error: Mapped[str] = mapped_column(Text, default='')
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
    attempted: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
def audit(db, actor, action, detail): db.add(Audit(actor=str(actor),action=action,detail=detail))
def eligible(c):
    if c.opted_out or not c.active or c.preference != "whatsapp": return False
    if c.kind=='customer' and c.consent=='verified' and c.scope=='marketing' and c.iys_status=='external_verified':
        return c.source=='HYS harici satış programı' and c.evidence.startswith('external_marketing_export:')
    if c.consent != "verified" or not c.evidence or not c.source or not c.consent_date: return False
    if c.kind == "customer": return c.scope == "marketing" and c.iys_status == "manual_verified"
    return c.scope == "staff" and bool(c.legal_basis)
