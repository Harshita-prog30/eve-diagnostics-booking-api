from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.deps import get_current_user
from app.models import Centre, CentreTest, Test, User
from app import schemas

router = APIRouter(prefix="/centres", tags=["centres"])

def to_out(c: Centre) -> schemas.CentreOut:
    return schemas.CentreOut(id=c.id, name=c.name, location=c.location, tests=[
        schemas.OfferingOut(test_id=o.test_id, price=o.price, test_name=o.test.name) for o in c.offerings])

def _load():
    return selectinload(Centre.offerings).selectinload(CentreTest.test)

@router.post("/", response_model=schemas.CentreOut, status_code=201)
def create_centre(body: schemas.CentreCreate, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    c = Centre(**body.model_dump()); db.add(c); db.commit(); db.refresh(c)
    return to_out(c)

@router.post("/{centre_id}/tests", response_model=schemas.CentreOut, status_code=201)
def add_test(centre_id: int, body: schemas.CentreTestCreate, db: Session = Depends(get_db),
             _: User = Depends(get_current_user)):
    centre = db.get(Centre, centre_id)
    if not centre:
        raise HTTPException(404, "Centre not found")
    test = db.scalar(select(Test).where(Test.name == body.test_name))
    if not test:
        test = Test(name=body.test_name); db.add(test); db.flush()
    if db.scalar(select(CentreTest).where(CentreTest.centre_id == centre_id, CentreTest.test_id == test.id)):
        raise HTTPException(409, "Centre already offers this test")
    db.add(CentreTest(centre_id=centre_id, test_id=test.id, price=body.price))
    db.commit(); db.refresh(centre)
    return to_out(centre)

@router.get("/", response_model=list[schemas.CentreOut])
def list_centres(location: str | None = None, limit: int = Query(20, ge=1, le=100),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    q = select(Centre).options(_load()).order_by(Centre.id).limit(limit).offset(offset)
    if location:
        q = q.where(Centre.location.ilike(f"%{location}%"))
    return [to_out(c) for c in db.scalars(q)]

@router.get("/{centre_id}", response_model=schemas.CentreOut)
def get_centre(centre_id: int, db: Session = Depends(get_db)):
    c = db.scalar(select(Centre).options(_load()).where(Centre.id == centre_id))
    if not c:
        raise HTTPException(404, "Centre not found")
    return to_out(c)