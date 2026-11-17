"""
Farmer login and profile.
The report and herd-breakdown endpoints now live in swine_reports.py, which
imports current_farmer and load_population from here.
"""
import os, time
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from database import get_db   # your own DB session dependency

router = APIRouter(prefix="/api", tags=["Farmer Livestock"])

SECRET = os.getenv("FARMER_JWT_SECRET", "change-me")   # set FARMER_JWT_SECRET before production
CATS = ["boar", "sow", "gilts", "piglets", "grower_fattener"]


class FarmerLogin(BaseModel):
    farmer_id: int


def current_farmer(authorization: str = Header(default="")) -> int:
    try:
        token = authorization.removeprefix("Bearer ")
        return int(jwt.decode(token, SECRET, algorithms=["HS256"])["sub"])
    except Exception:
        raise HTTPException(401, "Please log in again.")


def load_population(db, farmer_id: int) -> dict:
    """The farmer's current count = their latest VERIFIED report (vw_swine_latest).
    A farmer with no verified report yet gets zeros, so login still works."""
    row = db.execute(text("""
        SELECT swine_population, boar, sow, gilts, piglets, grower_fattener, unclassified
        FROM vw_swine_latest
        WHERE farmer_id = :fid
    """), {"fid": farmer_id}).mappings().first()
    if not row:
        return {"total": 0, "has_breakdown": False, "unclassified": 0, **{c: 0 for c in CATS}}
    cats = {c: row[c] or 0 for c in CATS}
    return {
        "total": row["swine_population"] or 0,
        "has_breakdown": sum(cats.values()) > 0,
        "unclassified": row["unclassified"] or 0,
        **cats,
    }


@router.post("/farmer-login")
def farmer_login(req: FarmerLogin, db=Depends(get_db)):
    farmer = db.execute(text(
        "SELECT id FROM tblfarmerregistry WHERE id = :fid"
    ), {"fid": req.farmer_id}).first()
    if not farmer:
        raise HTTPException(401, "Login failed: invalid farmer credentials.")
    token = jwt.encode(
        {"sub": str(farmer.id), "exp": int(time.time()) + 3600},
        SECRET, algorithm="HS256",
    )
    return {"success": True, "message": "Login successful.", "token": token}


@router.get("/farmer/me")
def farmer_me(farmer_id: int = Depends(current_farmer), db=Depends(get_db)):
    f = db.execute(text("""
        SELECT farmer_name, barangay, municipality, province
        FROM tblfarmerregistry WHERE id = :fid
    """), {"fid": farmer_id}).mappings().first()
    if not f:
        raise HTTPException(404, "Farmer not found.")
    pop = load_population(db, farmer_id)
    address = ", ".join(x for x in [f["barangay"], f["municipality"], f["province"]] if x)
    return {"farmer_name": f["farmer_name"], "address": address, "population": pop}