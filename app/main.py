import logging
from fastapi import FastAPI
from app.database import Base, engine
from app.routers import auth, centres, bookings, payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
Base.metadata.create_all(engine)   # simple for the assignment; use Alembic in production

app = FastAPI(title="EVE Diagnostics Booking API", version="1.0")
for r in (auth.router, centres.router, bookings.router, payments.router):
    app.include_router(r)

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}