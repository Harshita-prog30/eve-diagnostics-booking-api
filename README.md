# EVE Diagnostics Booking API

A small backend service for booking diagnostic tests and processing simulated payments.
Built with **FastAPI, PostgreSQL, SQLAlchemy 2.0 and JWT auth**.

Highlights:
- JWT signup/login with validated requests
- Diagnostic centres, tests and per-centre pricing
- Bookings with ownership checks
- Simulated payments (`SUCCESS` / `FAILED`)
- **Idempotent, signature-verified payment webhook**
- Dockerised, Swagger docs, pagination, tests, structured logging

---

## 1. Run locally

### Option A: Docker (recommended)

```bash
docker compose up --build
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

### Option B: Manual

Requires Python 3.12+ and a running PostgreSQL.

```bash
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# create DB/user matching DATABASE_URL below, then:
uvicorn app.main:app --reload
```

### Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://eve:eve@localhost:5432/eve` | Postgres connection string |
| `JWT_SECRET` | `change-me` | Use a random value of 32+ characters outside local dev |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `WEBHOOK_SECRET` | `whsec_dev` | Shared HMAC secret with the payment provider |

### Run tests

```bash
python -m pytest -q
```

Tests run against in-memory SQLite, so no Postgres is needed.

---

## 2. API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup` | No | Register a user |
| POST | `/auth/login` | No | Get a JWT access token |
| POST | `/centres/` | Yes | Create a centre |
| POST | `/centres/{id}/tests` | Yes | Add a test (with price) to a centre |
| GET | `/centres/` | No | List centres (`?location=`, `limit`, `offset`) |
| GET | `/centres/{id}` | No | Centre details with tests and prices |
| POST | `/bookings/` | Yes | Create a booking (starts as `PENDING`) |
| GET | `/bookings/` | Yes | List my bookings (paginated) |
| GET | `/bookings/{id}` | Yes | Get one of my bookings |
| POST | `/bookings/{id}/cancel` | Yes | Cancel my booking |
| POST | `/payments/` | Yes | Simulate a payment for a booking |
| POST | `/payments/webhook/` | HMAC signature | Payment provider status updates |
| GET | `/health` | No | Health check |

### Example requests (curl)

```bash
# Signup
curl -X POST localhost:8000/auth/signup -H "Content-Type: application/json" \
  -d '{"email":"a@x.com","full_name":"Asha","password":"password123"}'

# Login -> {"access_token": "...", "token_type": "bearer"}
curl -X POST localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"email":"a@x.com","password":"password123"}'

TOKEN=<access_token>

# Create centre, then add a test
curl -X POST localhost:8000/centres/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"City Labs","location":"Gurugram"}'
curl -X POST localhost:8000/centres/1/tests -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"test_name":"CBC","price":"499.00"}'

# Book (test_id comes from GET /centres/1)
curl -X POST localhost:8000/bookings/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-12-01T10:00:00Z"}'

# Pay (omit simulate_outcome for random ~80% success)
curl -X POST localhost:8000/payments/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"booking_id":1,"simulate_outcome":"SUCCESS"}'
```

### Webhook example

The provider signs the **raw request body** with HMAC-SHA256 using `WEBHOOK_SECRET` and sends it in `X-Signature`.

```bash
BODY='{"event_id":"evt_1","provider_ref":"<provider_ref from payment>","status":"SUCCESS"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "whsec_dev" | awk '{print $2}')
curl -X POST localhost:8000/payments/webhook/ \
  -H "X-Signature: $SIG" -H "Content-Type: application/json" -d "$BODY"
```

PowerShell equivalent:

```powershell
$body = '{"event_id":"evt_1","provider_ref":"<ref>","status":"SUCCESS"}'
$h = New-Object System.Security.Cryptography.HMACSHA256
$h.Key = [Text.Encoding]::UTF8.GetBytes("whsec_dev")
$sig = ([BitConverter]::ToString($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($body))) -replace '-','').ToLower()
Invoke-RestMethod -Method Post -Uri http://localhost:8000/payments/webhook/ `
  -Headers @{"X-Signature"=$sig} -ContentType "application/json" -Body $body
```

Sending the same `event_id` twice returns `{"status": "duplicate_ignored"}` the second time.

Typical error responses: `401` bad/expired token or bad webhook signature, `404` unknown/not-owned booking or unknown payment ref, `409` conflict (duplicate email, booking not payable), `422` validation error.

---

## 3. Database design

```
users 1──* bookings *──1 centre_tests *──1 centres
                              │
                              *──1 tests
bookings 1──* payments
webhook_events (event_id UNIQUE)
```

| Table | Purpose |
|---|---|
| `users` | Account, bcrypt-hashed password, unique email |
| `centres` | Diagnostic centre name and location |
| `tests` | Test catalogue (unique name) |
| `centre_tests` | Which centre offers which test, **and its price**. Unique `(centre_id, test_id)` |
| `bookings` | User, centre_test, appointment time, amount, status |
| `payments` | Payment attempts per booking, with a unique `provider_ref` |
| `webhook_events` | Processed webhook event IDs (idempotency key) |

Design decisions:
- **Price lives on `centre_tests`**, because the same test costs different amounts at different centres.
- **`bookings.amount` is a snapshot** of the price at booking time, so later price changes don't rewrite history.
- **`payments` is separate from `bookings`**, because a failed payment can be retried, giving several attempts per booking.
- **`webhook_events.event_id` is UNIQUE**, so idempotency is enforced by the database even under concurrent deliveries.
- Money uses `Numeric(10,2)`, never floats. All timestamps are timezone-aware (UTC).

### Booking status and payment rules

All state changes go through one function, `apply_payment_result()` in `app/services/payments.py`. Both `POST /payments/` and the webhook use it, so they can never disagree.

| Situation | Result |
|---|---|
| Payment `SUCCESS` | Payment `SUCCESS`, booking `CONFIRMED` |
| Payment `FAILED` while booking `PENDING` | Booking `FAILED` (user may retry payment) |
| Same status replayed | No-op |
| `FAILED` event after a payment already `SUCCESS` | Ignored (success is terminal) |
| Late `SUCCESS` for a previously `FAILED` payment | Booking becomes `CONFIRMED` |
| Payment resolves for a `CANCELLED` booking | Booking stays `CANCELLED`; warning logged (needs refund) |
| Pay for a `CONFIRMED` or `CANCELLED` booking | `409` |

### Idempotency and safety

1. **HMAC signature check** (constant-time compare) so only the provider can call the webhook.
2. **Unique `event_id` insert**: duplicates hit the unique constraint and return `200 duplicate_ignored`, so the provider stops retrying.
3. **State rules above**, so a *different* event for the same payment still can't corrupt state.
4. **Row locks** (`SELECT ... FOR UPDATE`) on the booking when paying and on the payment in the webhook, preventing double-pay races.
5. If the payment reference is unknown, the event record is rolled back and `404` is returned, so a later retry can still succeed.

Other safeguards: bookings owned by another user return `404` (not `403`) so IDs cannot be probed; login returns the same error for unknown email and wrong password; appointments must be in the future.

---

## 4. Project structure

```
app/
  main.py  config.py  database.py  models.py  schemas.py  security.py  deps.py
  routers/   auth.py  centres.py  bookings.py  payments.py
  services/  payments.py        # payment/booking state machine
tests/       conftest.py  test_api.py
```

Routers stay thin; business rules for payment state live in the service layer.

---

## 5. Assumptions

- Any authenticated user can create centres and add tests (no admin role yet).
- A centre offers each test at one price; the booking stores the price at booking time.
- Appointment times are stored in UTC; naive datetimes are treated as UTC.
- Payments are simulated; `simulate_outcome` exists only to make tests deterministic.
- Cancelling a paid booking does not trigger a refund.
- There is no slot-capacity model, so multiple users can book the same time.
- Tables are created at startup with `create_all` (fine for this scope).

## 6. What I would improve with more time

- Alembic migrations instead of `create_all`
- Role-based access (admin-only centre/test management)
- Async webhook processing with Celery, retries with backoff and a dead-letter table
- Redis caching for centre listings, and rate limiting on login
- Refresh tokens and token revocation
- Refund flow and a `REFUNDED` status
- Slot capacity per centre to prevent double booking, plus a reschedule endpoint
- Webhook timestamp checks to prevent replay of old signed requests
- CI pipeline running tests and linting