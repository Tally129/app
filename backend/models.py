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


def new_id() -> str:
    return str(uuid.uuid4())
