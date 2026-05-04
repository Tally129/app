from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Literal, Dict, Any, Annotated
from datetime import datetime
import uuid
from email_validator import validate_email, EmailNotValidError


Role = Literal["admin", "practitioner", "staff", "client"]


# Custom email validator that allows .local and .test domains for development/testing
def validate_test_email(v: str) -> str:
    """Allow .local, .test, etc., for development. Permissive for testing."""
    try:
        validated = validate_email(
            v,
            check_deliverability=False,  # Skip MX checks for speed/testing
            test_environment=True        # Allows special domains like .test
        )
        return validated.email.lower()  # Normalized email
    except EmailNotValidError as e:
        # For development, allow .local domains even if email-validator rejects them
        if v and '@' in v and (v.lower().endswith('.local') or v.lower().endswith('.localhost')):
            return v.lower()
        raise ValueError(f"Invalid email: {e}")


# Use str with custom validator instead of EmailStr for development compatibility
TestEmailStr = str


# --------- Users ---------
class UserBase(BaseModel):
    email: TestEmailStr
    full_name: str
    phone: Optional[str] = None
    role: Role = "client"
    
    @field_validator('email')
    @classmethod
    def validate_email_field(cls, v: str) -> str:
        return validate_test_email(v)


class UserCreate(UserBase):
    password: str = Field(min_length=8)


class UserOut(UserBase):
    id: str
    mfa_enabled: bool = False
    is_active: bool = True
    created_at: datetime
    last_login_at: Optional[datetime] = None


class LoginIn(BaseModel):
    email: TestEmailStr
    password: str
    mfa_token: Optional[str] = None
    
    @field_validator('email')
    @classmethod
    def validate_email_field(cls, v: str) -> str:
        return validate_test_email(v)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    user: UserOut
    mfa_required: bool = False


class RefreshIn(BaseModel):
    refresh_token: str


class MfaVerifyIn(BaseModel):
    token: str


# --------- Clients ---------
class ClientIn(BaseModel):
    user_id: Optional[str] = None  # if created by staff, link later
    full_name: Optional[str] = None
    email: Optional[TestEmailStr] = None
    phone: Optional[str] = None
    dob: Optional[str] = None
    sex: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: Optional[str] = None
    assigned_practitioner_id: Optional[str] = None
    
    @field_validator('email')
    @classmethod
    def validate_email_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return validate_test_email(v)


class ClientOut(ClientIn):
    id: str
    intake_completed: bool = False
    created_at: datetime


# --------- Intake ---------
class IntakeIn(BaseModel):
    client_id: Optional[str] = None  # resolved to self for clients
    demographics: Dict[str, Any] = {}
    health_history: Dict[str, Any] = {}
    symptoms: Dict[str, Any] = {}
    lifestyle: Dict[str, Any] = {}
    consent: Dict[str, Any] = {}  # signed: bool, signature: str, signed_at
    completed: bool = False


class IntakeOut(IntakeIn):
    id: str
    client_id: str
    signed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


# --------- SOAP Notes ---------
class NoteIn(BaseModel):
    client_id: str
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


class Amendment(BaseModel):
    author_id: str
    author_name: Optional[str] = None
    content: str
    ts: datetime


class NoteOut(NoteIn):
    id: str
    practitioner_id: str
    practitioner_name: Optional[str] = None
    created_at: datetime
    amendments: List[Amendment] = []


class AmendIn(BaseModel):
    content: str


# --------- Files ---------
class FileMetaOut(BaseModel):
    id: str
    filename: str
    mime: str
    size: int
    category: str
    client_id: Optional[str] = None
    uploaded_by: str
    uploaded_by_name: Optional[str] = None
    created_at: datetime


# --------- Appointments ---------
class AppointmentRequestIn(BaseModel):
    fullName: str
    email: Optional[str] = None
    phone: Optional[str] = None
    returning: Optional[str] = None
    service: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None
    addOns: List[str] = []


class VipSignupIn(BaseModel):
    email: TestEmailStr
    
    @field_validator('email')
    @classmethod
    def validate_email_field(cls, v: str) -> str:
        return validate_test_email(v)


# --------- Audit ---------
class AuditLogOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Dict[str, Any] = {}
    ts: datetime



# =========== PHASE 2 ===========

# --------- Appointments (real) ---------
AppointmentStatus = Literal["requested", "confirmed", "completed", "canceled", "no_show"]


class AppointmentIn(BaseModel):
    client_id: str
    practitioner_id: Optional[str] = None
    service: Optional[str] = None
    start: datetime  # ISO
    end: datetime
    notes: Optional[str] = None
    status: AppointmentStatus = "confirmed"
    visit_mode: Literal["in_person", "telehealth"] = "in_person"
    consent_telehealth: bool = False


class AppointmentUpdate(BaseModel):
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    service: Optional[str] = None
    practitioner_id: Optional[str] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    practitioner_id: Optional[str] = None
    practitioner_name: Optional[str] = None
    service: Optional[str] = None
    start: datetime
    end: datetime
    status: AppointmentStatus
    notes: Optional[str] = None
    visit_mode: Literal["in_person", "telehealth"] = "in_person"
    consent_telehealth: bool = False
    telehealth: Optional[Dict[str, Any]] = None
    created_at: datetime
    created_by: Optional[str] = None


# --------- Availability (recurring weekly) ---------
class AvailabilityIn(BaseModel):
    practitioner_id: Optional[str] = None  # defaults to self
    weekday: int  # 0=Mon .. 6=Sun
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    active: bool = True


class AvailabilityOut(AvailabilityIn):
    id: str
    practitioner_id: str


# --------- Memberships ---------
MembershipStatus = Literal["pending", "active", "paused", "canceled"]
BillingMethod = Literal["stripe", "chase_pos", "manual"]


class MembershipIn(BaseModel):
    client_id: Optional[str] = None  # defaults to self for clients
    tier: str  # essentials|core|vip
    billing_method: BillingMethod = "chase_pos"


class MembershipOut(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    tier: str
    price: float
    status: MembershipStatus
    billing_method: BillingMethod
    started_at: Optional[datetime] = None
    next_bill_date: Optional[datetime] = None
    stripe_subscription_id: Optional[str] = None
    created_at: datetime


# --------- Invoices ---------
InvoiceStatus = Literal["due", "paid", "void"]
PaymentMethod = Literal["stripe", "chase_pos_manual", "other"]


class InvoiceIn(BaseModel):
    client_id: str
    appointment_id: Optional[str] = None
    membership_id: Optional[str] = None
    description: str
    amount: float


class InvoiceOut(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    appointment_id: Optional[str] = None
    membership_id: Optional[str] = None
    description: str
    amount: float
    status: InvoiceStatus
    paid_at: Optional[datetime] = None
    payment_method: Optional[PaymentMethod] = None
    external_ref: Optional[str] = None
    created_at: datetime


class MarkPaidIn(BaseModel):
    method: PaymentMethod = "chase_pos_manual"
    external_ref: Optional[str] = None


# --------- Treatment Plans ---------
class PlanItem(BaseModel):
    type: Literal["supplement", "diet", "lifestyle", "lab_order", "follow_up"]
    title: str
    detail: Optional[str] = None
    dose: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    patient_visible: bool = True


class PlanIn(BaseModel):
    client_id: str
    title: str
    status: Literal["draft", "active", "completed"] = "active"
    follow_up_days: Optional[int] = None
    items: List[PlanItem] = []


class PlanOut(PlanIn):
    id: str
    practitioner_id: str
    practitioner_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# --------- Reminder settings ---------
class ReminderSettings(BaseModel):
    appointment_reminder_hours_before: int = 24
    appointment_reminder_channels: List[Literal["email", "sms"]] = ["email"]
    follow_up_days_after: int = 7
    enabled: bool = True


def new_id() -> str:
    return str(uuid.uuid4())


# =========== PHASE 3 + TELEHEALTH ===========

VisitMode = Literal["in_person", "telehealth"]


# Extend appointment models
class AppointmentInV2(AppointmentIn):  # type: ignore
    visit_mode: VisitMode = "in_person"
    consent_telehealth: bool = False


# --------- Symptom logs ---------
class SymptomLogIn(BaseModel):
    client_id: Optional[str] = None
    symptom: str
    severity: int = Field(ge=1, le=10)
    note: Optional[str] = None
    logged_at: Optional[datetime] = None


class SymptomLogOut(BaseModel):
    id: str
    client_id: str
    symptom: str
    severity: int
    note: Optional[str] = None
    logged_at: datetime
    created_at: datetime


# --------- Lab values ---------
class LabValueIn(BaseModel):
    client_id: str
    test_name: str
    value: float
    unit: Optional[str] = None
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    measured_at: datetime
    notes: Optional[str] = None


class LabValueOut(LabValueIn):
    id: str
    recorded_by: str
    recorded_by_name: Optional[str] = None
    created_at: datetime


# --------- Secure messaging ---------
class ThreadIn(BaseModel):
    participant_id: str  # the other party
    subject: str
    first_message: Optional[str] = None


class ThreadOut(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    practitioner_id: str
    practitioner_name: Optional[str] = None
    subject: str
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    unread_for_me: int = 0
    created_at: datetime


class MessageIn(BaseModel):
    body: str
    attachment_file_ids: List[str] = []


class MessageOut(BaseModel):
    id: str
    thread_id: str
    sender_id: str
    sender_role: str
    sender_name: Optional[str] = None
    body: str
    attachment_file_ids: List[str] = []
    read_by: List[str] = []
    created_at: datetime


# =========== PHASE 4: TREATMENTS / POS / INVENTORY / TIME CLOCK / FRONT DESK / IMPORT ===========


class TreatmentIn(BaseModel):
    name: str
    category: Optional[str] = None
    duration_min: int = 60
    price: float
    sku: Optional[str] = None
    description: Optional[str] = None
    active: bool = True


class TreatmentOut(TreatmentIn):
    id: str
    created_at: datetime


class InventoryItemIn(BaseModel):
    name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    stock: int = 0
    unit_price: float = 0.0
    low_stock_threshold: int = 5
    active: bool = True


class InventoryItemOut(InventoryItemIn):
    id: str
    created_at: datetime


class InventoryAdjustIn(BaseModel):
    delta: int
    reason: str = "manual"
    note: Optional[str] = None


PosLineType = Literal["treatment", "inventory", "custom"]
PosPaymentMethod = Literal["chase_pos", "cash", "check", "card_other", "stripe"]


class PosLine(BaseModel):
    type: PosLineType
    ref_id: Optional[str] = None
    name: str
    qty: int = 1
    unit_price: float


class PosCheckoutIn(BaseModel):
    client_id: Optional[str] = None
    lines: List[PosLine]
    discount: float = 0.0
    tip: float = 0.0
    tax_rate: float = 0.0
    payment_method: PosPaymentMethod = "chase_pos"
    payment_ref: Optional[str] = None
    note: Optional[str] = None


class PosLineOut(PosLine):
    line_total: float


class TransactionOut(BaseModel):
    id: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    lines: List[PosLineOut]
    subtotal: float
    discount: float
    tip: float
    tax: float
    total: float
    payment_method: str
    payment_ref: Optional[str] = None
    status: str
    paid_at: Optional[datetime] = None
    note: Optional[str] = None
    created_by: str
    created_by_name: Optional[str] = None
    created_at: datetime


# Time Clock
class TimeBreak(BaseModel):
    start: datetime
    end: Optional[datetime] = None


class TimeEntryOut(BaseModel):
    id: str
    user_id: str
    user_name: Optional[str] = None
    clock_in: datetime
    clock_out: Optional[datetime] = None
    breaks: List[TimeBreak] = []
    total_minutes: Optional[float] = None
    note: Optional[str] = None
    edited_by: Optional[str] = None


class TimeEditIn(BaseModel):
    clock_in: Optional[datetime] = None
    clock_out: Optional[datetime] = None
    note: Optional[str] = None


# Front Desk
FrontDeskStatus = Literal["scheduled", "checked_in", "in_room", "checked_out", "no_show"]


class FrontDeskCheckIn(BaseModel):
    client_id: str
    appointment_id: Optional[str] = None
    walk_in: bool = False
    room: Optional[str] = None


class FrontDeskUpdate(BaseModel):
    status: Optional[FrontDeskStatus] = None
    room: Optional[str] = None


class FrontDeskOut(BaseModel):
    id: str
    client_id: str
    client_name: Optional[str] = None
    appointment_id: Optional[str] = None
    walk_in: bool = False
    status: FrontDeskStatus
    room: Optional[str] = None
    checked_in_at: Optional[datetime] = None
    checked_out_at: Optional[datetime] = None
    created_at: datetime


# Account / password
class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


# --------- Telehealth ---------
class TelehealthConsentIn(BaseModel):
    signature: str

