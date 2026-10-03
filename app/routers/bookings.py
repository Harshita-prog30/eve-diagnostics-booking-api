from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.deps import get_current_user
from app.models import Booking, BookingStatus, CentreTest, User
from app import schemas

router = APIRouter(prefix="/bookings", tags=["bookings"])

def to_out(b: Booking) -> schemas.BookingOut:
    return schemas.BookingOut(id=b.id, user_id=b.user_id, centre_id=b.centre_test.centre_id,
        test_id=b.centre_test.test_id, appointment_at=b.appointment_at, amount=b.amount, status=b.status)

def get_owned_booking(db: Session, booking_id: int, user: User, lock=False) -> Booking:
    q = select(Booking).options(joinedload(Booking.centre_test)).where(
        Booking.id == booking_id, Booking.user_id == user.id)
    if lock:
        q = q.with_for_update(of=Booking)
    b = db.scalar(q)
    if not b:
        raise HTTPException(404, "Booking not found")
    return b

@router.post("/", response_model=schemas.BookingOut, status_code=201)
def create_booking(body: schemas.BookingCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    appt = body.appointment_at
    if appt.tzinfo is None:
        appt = appt.replace(tzinfo=timezone.utc)
    if appt <= datetime.now(timezone.utc):
        raise HTTPException(422, "Appointment must be in the future")
    ct = db.scalar(select(CentreTest).where(
        CentreTest.centre_id == body.centre_id, CentreTest.test_id == body.test_id))
    if not ct:
        raise HTTPException(404, "This centre does not offer this test")
    b = Booking(user_id=user.id, centre_test_id=ct.id, appointment_at=appt, amount=ct.price)
    db.add(b); db.commit(); db.refresh(b)
    return to_out(b)

@router.get("/", response_model=list[schemas.BookingOut])
def my_bookings(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = (select(Booking).options(joinedload(Booking.centre_test)).where(Booking.user_id == user.id)
         .order_by(Booking.id.desc()).limit(limit).offset(offset))
    return [to_out(b) for b in db.scalars(q)]

@router.get("/{booking_id}", response_model=schemas.BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return to_out(get_owned_booking(db, booking_id, user))

@router.post("/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = get_owned_booking(db, booking_id, user, lock=True)
    if b.status == BookingStatus.CANCELLED:
        raise HTTPException(409, "Booking already cancelled")
    b.status = BookingStatus.CANCELLED
    db.commit(); db.refresh(b)
    return to_out(b)