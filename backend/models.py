from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Literal, Dict, Any, Annotated
from datetime import datetime
import uuid
from email_validator import validate_email, EmailNotValidError


Role = Literal["admin", "practitioner", "staff", "client", "auditor"]


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
    # NIST validator (validate_password_strength) is the single source of truth; keep Pydantic lax so the clean 400 wins over 422.
    password: str = Field(min_length=1)


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
    # EHR-style extended fields (all optional, used by Add Patient wizard)
    mrn: Optional[str] = None  # auto-generated client/patient ID
    photo_file_id: Optional[str] = None
    gender_identity: Optional[str] = None
    pronouns: Optional[str] = None
    language: Optional[str] = None
    marital_status: Optional[str] = None
    alt_phone: Optional[str] = None
    referral_source: Optional[str] = None
    primary_concern: Optional[str] = None
    wellness_goals: Optional[str] = None
    current_supplements: Optional[str] = None
    dietary_restrictions: Optional[str] = None
    allergies: Optional[str] = None
    comms_pref: Optional[str] = None  # email | sms | phone
    consent_telehealth: Optional[bool] = None
    consent_photo: Optional[bool] = None
    consent_marketing: Optional[bool] = None
    notes: Optional[str] = None
    
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
    reason: Optional[str] = None
    ts: datetime


class NoteOut(NoteIn):
    id: str
    practitioner_id: str
    practitioner_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    amendments: List[Amendment] = []
    status: Optional[str] = "draft"
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[str] = None
    prior_versions: List[Dict[str, Any]] = []


class AmendIn(BaseModel):
    content: str
    reason: Optional[str] = None


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
    sha256: Optional[str] = None
    scan_status: Optional[str] = None
    scan_engine: Optional[str] = None
    scanned_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


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
AppointmentStatus = Literal["requested", "scheduled", "confirmed", "arrived", "in_session", "completed", "canceled", "no_show"]


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
    lifecycle_status: Optional[str] = "draft"
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[str] = None
    amendments: List[Dict[str, Any]] = []
    prior_versions: List[Dict[str, Any]] = []


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
    # NIST validator enforces ≥12 chars + name/common-password checks; keep Pydantic lax so users see the clean 400.
    new_password: str = Field(min_length=1)


# --------- Telehealth ---------
class TelehealthConsentIn(BaseModel):
    signature: str


# =========== PHASE 10: FORMS & CONSENTS ===========

FormCategory = Literal["consent", "intake", "hipaa", "photo_release", "treatment", "other"]
FormFieldType = Literal["text", "textarea", "date", "checkbox", "radio", "select", "signature", "email", "phone", "number"]


class FormField(BaseModel):
    id: str
    type: FormFieldType
    label: str
    required: bool = False
    placeholder: Optional[str] = None
    options: List[str] = []  # for radio/select
    help_text: Optional[str] = None


class FormTemplateIn(BaseModel):
    title: str
    description: Optional[str] = ""
    category: FormCategory = "other"
    fields: List[FormField] = []
    active: bool = True


class FormTemplateOut(FormTemplateIn):
    id: str
    builtin: bool = False
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class FormTranscribeOut(BaseModel):
    title: str
    description: str = ""
    category: FormCategory = "other"
    fields: List[FormField] = []
    source: str = "ai"  # ai | upload | manual
    extracted_text_preview: Optional[str] = None


class FormGenerateIn(BaseModel):
    prompt: str
    category: Optional[FormCategory] = "other"


class FormSendIn(BaseModel):
    template_id: str
    client_id: Optional[str] = None  # if known
    appointment_id: Optional[str] = None
    expires_in_hours: int = 168  # 7 days default
    note: Optional[str] = None
    channel: Literal["link", "email", "sms"] = "link"
    delivery_target: Optional[str] = None  # email or phone — auto-resolved from client if blank


class FormSubmissionAnswers(BaseModel):
    answers: Dict[str, Any] = {}
    signature_data: Optional[str] = None  # data:image/png;base64,...


class FormSubmissionOut(BaseModel):
    id: str
    template_id: str
    template_title: Optional[str] = None
    template_category: Optional[FormCategory] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    appointment_id: Optional[str] = None
    sent_by_id: Optional[str] = None
    sent_by_name: Optional[str] = None
    answers: Dict[str, Any] = {}
    signature_data: Optional[str] = None
    status: Literal["sent", "submitted", "expired", "void"] = "sent"
    lifecycle_status: Optional[str] = None
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[str] = None
    amendments: List[Dict[str, Any]] = []
    prior_versions: List[Dict[str, Any]] = []
    token: Optional[str] = None
    submit_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    channel: Optional[str] = None
    delivery_target: Optional[str] = None
    delivery_status: Optional[str] = None


class FormPublicOut(BaseModel):
    """What an unauthenticated responder sees."""
    template_id: str
    title: str
    description: str
    category: FormCategory
    fields: List[FormField]
    client_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    already_submitted: bool = False


# =========== PHASE 11: SOAP TEMPLATES ===========


class SoapTemplateIn(BaseModel):
    title: str
    description: Optional[str] = ""
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    visit_type: Optional[str] = None  # 'telehealth' | 'in_person' | None=any
    active: bool = True


class SoapTemplateOut(SoapTemplateIn):
    id: str
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# =========== PHASE 11: PROTOCOLS (DETOX & CUSTOM) ===========

ProtocolStatus = Literal["proposed", "accepted", "active", "completed", "canceled", "declined"]


class ProtocolSessionDef(BaseModel):
    """One slot in the protocol grid (week N, session M)."""
    week: int
    session: int  # 1..N within the week
    label: Optional[str] = None  # optional override per slot


class ProtocolTemplateIn(BaseModel):
    title: str
    description: Optional[str] = ""
    weeks: int = Field(ge=1, le=52, default=4)
    sessions_per_week: int = Field(ge=1, le=14, default=1)
    daily_outline: Optional[str] = ""  # markdown / freeform
    foods_recommended: List[str] = []
    foods_avoid: List[str] = []
    supplements: List[Dict[str, Any]] = []  # [{name, dose, frequency, notes}]
    lifestyle: Optional[str] = ""
    treatment_label: Optional[str] = "Treatment session"
    active: bool = True


class ProtocolTemplateOut(ProtocolTemplateIn):
    id: str
    builtin: bool = False
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProtocolSession(BaseModel):
    """Realized session attached to an enrollment."""
    week: int
    session: int  # 1..sessions_per_week
    label: Optional[str] = None
    completed: bool = False
    completed_at: Optional[datetime] = None
    completed_by_id: Optional[str] = None
    completed_by_name: Optional[str] = None
    notes: Optional[str] = None


class ProtocolEnrollmentIn(BaseModel):
    template_id: str
    client_id: str
    weeks: Optional[int] = None  # override template default
    sessions_per_week: Optional[int] = None
    custom_note: Optional[str] = None


class ProtocolEnrollmentOut(BaseModel):
    id: str
    template_id: str
    template_title: Optional[str] = None
    client_id: str
    client_name: Optional[str] = None
    practitioner_id: Optional[str] = None
    practitioner_name: Optional[str] = None
    weeks: int
    sessions_per_week: int
    status: ProtocolStatus
    sessions: List[ProtocolSession] = []
    snapshot: Dict[str, Any] = {}  # full template fields at enrollment time
    custom_note: Optional[str] = None
    proposed_at: datetime
    accepted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None


class ProtocolSessionUpdate(BaseModel):
    week: int
    session: int
    completed: Optional[bool] = None
    notes: Optional[str] = None


class ProtocolDecisionIn(BaseModel):
    decision: Literal["accept", "decline"]
    note: Optional[str] = None



