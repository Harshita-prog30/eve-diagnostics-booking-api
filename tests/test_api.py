import hashlib, hmac, json
from datetime import datetime, timedelta, timezone
from app.config import settings
from tests.conftest import make_user

def setup_booking(client, auth):
    c = client.post("/centres/", json={"name": "Lab", "location": "Gurugram"}, headers=auth).json()
    client.post(f"/centres/{c['id']}/tests", json={"test_name": "CBC", "price": "499.00"}, headers=auth)
    test_id = client.get(f"/centres/{c['id']}").json()["tests"][0]["test_id"]
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    b = client.post("/bookings/", json={"centre_id": c["id"], "test_id": test_id, "appointment_at": when}, headers=auth)
    assert b.status_code == 201
    return b.json()

def signed(payload: dict):
    raw = json.dumps(payload).encode()
    sig = hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"X-Signature": sig, "Content-Type": "application/json"}}

def test_signup_duplicate_and_bad_login(client):
    make_user(client)
    r = client.post("/auth/signup", json={"email": "a@x.com", "full_name": "A", "password": "password123"})
    assert r.status_code == 409
    assert client.post("/auth/login", json={"email": "a@x.com", "password": "wrong-pass"}).status_code == 401

def test_validation_and_auth_required(client):
    assert client.post("/auth/signup", json={"email": "bad", "full_name": "A", "password": "x"}).status_code == 422
    assert client.get("/bookings/").status_code in (401, 403)

def test_cannot_access_other_users_booking(client, auth):
    b = setup_booking(client, auth)
    other = make_user(client, "b@x.com")
    assert client.get(f"/bookings/{b['id']}", headers=other).status_code == 404
    assert client.post("/payments/", json={"booking_id": b["id"]}, headers=other).status_code == 404
    assert client.get("/bookings/9999", headers=auth).status_code == 404

def test_payment_success_confirms_booking(client, auth):
    b = setup_booking(client, auth)
    p = client.post("/payments/", json={"booking_id": b["id"], "simulate_outcome": "SUCCESS"}, headers=auth)
    assert p.json()["status"] == "SUCCESS"
    assert client.get(f"/bookings/{b['id']}", headers=auth).json()["status"] == "CONFIRMED"
    # cannot pay twice
    assert client.post("/payments/", json={"booking_id": b["id"]}, headers=auth).status_code == 409

def test_failed_payment_then_retry(client, auth):
    b = setup_booking(client, auth)
    client.post("/payments/", json={"booking_id": b["id"], "simulate_outcome": "FAILED"}, headers=auth)
    assert client.get(f"/bookings/{b['id']}", headers=auth).json()["status"] == "FAILED"
    client.post("/payments/", json={"booking_id": b["id"], "simulate_outcome": "SUCCESS"}, headers=auth)
    assert client.get(f"/bookings/{b['id']}", headers=auth).json()["status"] == "CONFIRMED"

def test_webhook_idempotent(client, auth):
    b = setup_booking(client, auth)
    p = client.post("/payments/", json={"booking_id": b["id"], "simulate_outcome": "FAILED"}, headers=auth).json()
    evt = signed({"event_id": "evt_1", "provider_ref": p["provider_ref"], "status": "SUCCESS"})
    r1 = client.post("/payments/webhook/", **evt)
    r2 = client.post("/payments/webhook/", **evt)
    assert r1.json()["status"] == "processed"
    assert r2.json()["status"] == "duplicate_ignored"
    assert client.get(f"/bookings/{b['id']}", headers=auth).json()["status"] == "CONFIRMED"

def test_webhook_cannot_downgrade_success(client, auth):
    b = setup_booking(client, auth)
    p = client.post("/payments/", json={"booking_id": b["id"], "simulate_outcome": "SUCCESS"}, headers=auth).json()
    r = client.post("/payments/webhook/", **signed({"event_id": "evt_2", "provider_ref": p["provider_ref"], "status": "FAILED"}))
    assert r.json()["status"] == "no_change"
    assert client.get(f"/bookings/{b['id']}", headers=auth).json()["status"] == "CONFIRMED"

def test_webhook_bad_signature_and_unknown_ref(client):
    r = client.post("/payments/webhook/", content=b"{}", headers={"X-Signature": "nope"})
    assert r.status_code == 401
    r = client.post("/payments/webhook/", **signed({"event_id": "e", "provider_ref": "zzz", "status": "SUCCESS"}))
    assert r.status_code == 404