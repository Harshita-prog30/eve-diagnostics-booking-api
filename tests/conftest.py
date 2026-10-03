import os
os.environ["DATABASE_URL"] = "sqlite://"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False)

def override_db():
    db = TestingSession()
    try: yield db
    finally: db.close()

@pytest.fixture()
def client():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()

def make_user(client, email="a@x.com"):
    client.post("/auth/signup", json={"email": email, "full_name": "A", "password": "password123"})
    tok = client.post("/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}

@pytest.fixture()
def auth(client): return make_user(client)