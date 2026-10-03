import hashlib, hmac, random
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import BookingStatus, Payment, PaymentStatus, User, WebhookEvent
from app.routers.bookings import get_owned_booking
from app.services.payments import apply_payment_result
from app import schemas

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/", response_model=schemas.PaymentOut, status_code=201)
def create_payment(body: schemas.PaymentCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    booking = get_owned_booking(db, body.booking_id, user, lock=True)  # row lock: no double-pay race
    if booking.status not in (BookingStatus.PENDING, BookingStatus.FAILED):
        raise HTTPException(409, f"Booking is {booking.status.value}; cannot be paid")
    payment = Payment(booking_id=booking.id, amount=booking.amount)
    db.add(payment); db.flush()
    outcome = body.simulate_outcome or ("SUCCESS" if random.random() < 0.8 else "FAILED")
    apply_payment_result(payment, PaymentStatus(outcome))
    db.commit(); db.refresh(payment)
    return payment

@router.post("/webhook/")
async def webhook(request: Request, x_signature: str = Header(...), db: Session = Depends(get_db)):
    raw = await request.body()
    expected = hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "Invalid signature")
    try:
        data = schemas.WebhookIn.model_validate_json(raw)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False))

    db.add(WebhookEvent(event_id=data.event_id, payload=raw.decode()))
    try:
        db.flush()                       # UNIQUE(event_id) enforces idempotency
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate_ignored"}   # 200 so the provider stops retrying

    payment = db.scalar(select(Payment).where(Payment.provider_ref == data.provider_ref).with_for_update())
    if not payment:
        db.rollback()                    # forget the event so a later retry can succeed
        raise HTTPException(404, "Unknown payment reference")
    changed = apply_payment_result(payment, PaymentStatus(data.status))
    db.commit()
    return {"status": "processed" if changed else "no_change"}