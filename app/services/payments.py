import logging
from app.models import Booking, BookingStatus, Payment, PaymentStatus

log = logging.getLogger("payments")

def apply_payment_result(payment: Payment, new_status: PaymentStatus) -> bool:
    """Single place where payment/booking state changes. Returns True if anything changed.

    Rules:
      - SUCCESS is terminal (never overwritten).
      - Same-status replays are no-ops.
      - A FAILED payment may later become SUCCESS (provider's late confirmation).
      - A late FAILED event for an old attempt never downgrades a CONFIRMED booking.
      - CANCELLED bookings are never revived.
    """
    if payment.status == new_status or payment.status == PaymentStatus.SUCCESS:
        return False
    payment.status = new_status
    booking: Booking = payment.booking

    if booking.status == BookingStatus.CANCELLED:
        log.warning("payment %s resolved for cancelled booking %s - needs refund", payment.id, booking.id)
    elif new_status == PaymentStatus.SUCCESS:
        booking.status = BookingStatus.CONFIRMED
    elif new_status == PaymentStatus.FAILED and booking.status == BookingStatus.PENDING:
        booking.status = BookingStatus.FAILED
    log.info("payment %s -> %s (booking %s is %s)", payment.id, new_status.value, booking.id, booking.status.value)
    return True