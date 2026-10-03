from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from app.models import BookingStatus, PaymentStatus

class SignupIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=72)   # bcrypt limit is 72 bytes

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str

class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)

class CentreTestCreate(BaseModel):
    test_name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)

class OfferingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    test_id: int
    price: Decimal
    test_name: str

class CentreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location: str
    tests: list[OfferingOut] = []

class BookingCreate(BaseModel):
    centre_id: int
    test_id: int
    appointment_at: datetime

class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    centre_id: int
    test_id: int
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus

class PaymentCreate(BaseModel):
    booking_id: int
    # test hook: force an outcome. Omit for random (~80% success).
    simulate_outcome: Optional[Literal["SUCCESS", "FAILED"]] = None

class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    booking_id: int
    provider_ref: str
    amount: Decimal
    status: PaymentStatus

class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    provider_ref: str
    status: Literal["SUCCESS", "FAILED"]