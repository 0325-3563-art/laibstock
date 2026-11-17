"""
Swine period reports (farmer + MAO staff), SQLAlchemy version.
Replaces src/backend/swine_reports.py. Needs swine_models.py in the same folder.

Tables/views used: tblswinereport, tblswinemovement, tblswinepopulation,
tblfarmerregistry, vw_swine_latest, vw_swine_reconciliation.
"""
import os
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from swine_models import CATS, IN_TYPES, PeriodReportBody, SwineReportIn
# Same login check and population lookup that /api/farmer/me uses.
from farmer_livestock import current_farmer as get_current_farmer_id
from farmer_livestock import load_population as current_population

engine = create_engine(os.environ["ASF_DATABASE_URL"], pool_pre_ping=True)
router = APIRouter()


# ====================================================================== helpers
def period_start(period_type: str, period_end: date) -> date:
    if period_type == "monthly":
        return period_end.replace(day=1)
    first_month = 3 * ((period_end.month - 1) // 3) + 1
    return date(period_end.year, first_month, 1)


def latest_period_end(conn, farmer_id: int):
    return conn.execute(
        text("SELECT MAX(period_end) FROM tblswinereport WHERE farmer_id = :f"),
        {"f": farmer_id},
    ).scalar()


def opening_before(conn, farmer_id: int, period_end: date):
    """Closing count of the last VERIFIED report before this period (None = first report)."""
    return conn.execute(
        text("""
            SELECT p.swine_population
            FROM tblswinereport r
            JOIN tblswinepopulation p ON p.report_id = r.id
            WHERE r.farmer_id = :f AND r.status = 'verified' AND r.period_end < :d
            ORDER BY r.period_end DESC
            LIMIT 1
        """),
        {"f": farmer_id, "d": period_end},
    ).scalar()


def sync_registry_total(conn, farmer_id: int):
    """Dashboards and the ML features read tblfarmerregistry.total_farm_population,
    so keep it equal to the latest verified report."""
    conn.execute(
        text("""
            UPDATE tblfarmerregistry
            SET total_farm_population = (
                SELECT swine_population FROM vw_swine_latest WHERE farmer_id = :f)
            WHERE id = :f
              AND EXISTS (SELECT 1 FROM vw_swine_latest WHERE farmer_id = :f)
        """),
        {"f": farmer_id},
    )


def insert_report(conn, *, farmer_id: int, body: PeriodReportBody, status: str,
                  role: str, user: Optional[str]) -> int:
    """Report + closing inventory + movements. The caller owns the transaction."""
    verified = status == "verified"
    report_id = conn.execute(
        text("""
            INSERT INTO tblswinereport
              (farmer_id, period_type, period_start, period_end, status,
               reported_by_role, reported_by_user, verified_by, verified_at, remarks)
            VALUES (:farmer_id, :period_type, :period_start, :period_end, :status,
                    :role, :user, :verified_by, :verified_at, :remarks)
            RETURNING id
        """),
        {
            "farmer_id": farmer_id,
            "period_type": body.period_type,
            "period_start": period_start(body.period_type, body.period_end),
            "period_end": body.period_end,
            "status": status,
            "role": role,
            "user": user,
            "verified_by": user if verified else None,
            "verified_at": datetime.now() if verified else None,
            "remarks": body.remarks,
        },
    ).scalar_one()

    # Closing inventory. Total-only: categories are 0, everything counts as "not broken down".
    is_total = body.report_mode == "total"
    conn.execute(
        text("""
            INSERT INTO tblswinepopulation
              (farmer_id, dateadded, swine_population, boar, sow, gilts, piglets, grower_fattener, report_id)
            VALUES (:farmer_id, :dateadded, :total, :boar, :sow, :gilts, :piglets, :grower_fattener, :report_id)
        """),
        {
            "farmer_id": farmer_id,
            "dateadded": body.period_end,
            "total": body.closing_total,
            "report_id": report_id,
            **{c: (0 if is_total else body.counts.get(c, 0)) for c in CATS},
        },
    )

    if body.movements:
        conn.execute(
            text("""
                INSERT INTO tblswinemovement (report_id, movement_type, category, quantity)
                VALUES (:report_id, :movement_type, :category, :quantity)
            """),
            [
                {"report_id": report_id, "movement_type": m.movement_type,
                 "category": m.category, "quantity": m.quantity}
                for m in body.movements
            ],
        )
    return report_id


def check_movements(conn, farmer_id: int, body: PeriodReportBody):
    """Swine cannot leave the farm in numbers larger than were on record."""
    opening = opening_before(conn, farmer_id, body.period_end) or 0
    total_in = sum(m.quantity for m in body.movements if m.movement_type in IN_TYPES)
    total_out = sum(m.quantity for m in body.movements if m.movement_type not in IN_TYPES)
    if total_out > opening + total_in:
        raise HTTPException(
            400, f"You reported {total_out} swine leaving, but only {opening + total_in} were on record."
        )


# ====================================================================== farmer
@router.post("/api/farmer/period-report")
def farmer_period_report(body: PeriodReportBody, farmer_id: int = Depends(get_current_farmer_id)):
    try:
        with engine.begin() as conn:
            # The farmer's on-hand count is calculated from the last VERIFIED count,
            # so the next report must wait until the previous one is reviewed.
            pending = conn.execute(
                text("""
                    SELECT period_end FROM tblswinereport
                    WHERE farmer_id = :f AND status = 'submitted'
                    ORDER BY period_end DESC LIMIT 1
                """),
                {"f": farmer_id},
            ).scalar()
            if pending:
                raise HTTPException(
                    400,
                    f"Your report for {pending:%B %d, %Y} is still waiting for MAO staff review. "
                    "You can send the next report once it is verified.",
                )

            last = latest_period_end(conn, farmer_id)
            if last and body.period_end <= last:
                raise HTTPException(
                    400,
                    f"Your latest report already covers up to {last:%B %d, %Y}. "
                    "Choose a later period, or ask MAO staff if you need to correct it.",
                )
            check_movements(conn, farmer_id, body)
            report_id = insert_report(
                conn, farmer_id=farmer_id, body=body, status="submitted",
                role="farmer", user=str(farmer_id),
            )
            population = current_population(conn, farmer_id)
    except IntegrityError:
        raise HTTPException(409, "A report for that date already exists.")

    # population is the latest VERIFIED count: it does not change until staff verify.
    return {"report_id": report_id, "status": "submitted", "population": population}


class BreakdownIn(BaseModel):
    boar: int = Field(0, ge=0)
    sow: int = Field(0, ge=0)
    gilts: int = Field(0, ge=0)
    piglets: int = Field(0, ge=0)
    grower_fattener: int = Field(0, ge=0)


@router.post("/api/farmer/herd-breakdown")
def farmer_herd_breakdown(body: BreakdownIn, farmer_id: int = Depends(get_current_farmer_id)):
    """Split animals that are counted in the total but not yet assigned to a category.
    Changes only the category columns of the latest VERIFIED count. The total never changes."""
    add = body.model_dump()
    added = sum(add.values())
    if added <= 0:
        raise HTTPException(400, "Enter at least one animal.")

    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT p.id, p.swine_population,
                       COALESCE(p.boar,0) AS boar, COALESCE(p.sow,0) AS sow,
                       COALESCE(p.gilts,0) AS gilts, COALESCE(p.piglets,0) AS piglets,
                       COALESCE(p.grower_fattener,0) AS grower_fattener
                FROM tblswinereport r
                JOIN tblswinepopulation p ON p.report_id = r.id
                WHERE r.farmer_id = :f AND r.status = 'verified'
                ORDER BY r.period_end DESC, r.id DESC
                LIMIT 1
                FOR UPDATE OF p
            """),
            {"f": farmer_id},
        ).mappings().first()
        if not row:
            raise HTTPException(400, "There is no verified swine count on record yet.")

        unclassified = row["swine_population"] - sum(row[c] for c in CATS)
        if added > unclassified:
            raise HTTPException(
                400, f"You can only assign up to {max(unclassified, 0)} swine that are not broken down yet."
            )

        conn.execute(
            text("""
                UPDATE tblswinepopulation
                SET boar = :boar, sow = :sow, gilts = :gilts,
                    piglets = :piglets, grower_fattener = :grower_fattener
                WHERE id = :id
            """),
            {"id": row["id"], **{c: row[c] + add[c] for c in CATS}},
        )
        population = current_population(conn, farmer_id)

    return {"population": population}


# ====================================================================== staff
@router.get("/swine/farmers")
def search_farmers(q: str = Query("")):
    q = q.strip()
    if len(q) < 2:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, farmer_name, municipality, barangay
                FROM tblfarmerregistry
                WHERE farmer_name ILIKE :like OR CAST(id AS text) = :exact
                ORDER BY farmer_name
                LIMIT 15
            """),
            {"like": f"%{q}%", "exact": q},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/swine/opening")
def get_opening(farmer_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT period_end, swine_population FROM vw_swine_latest WHERE farmer_id = :f"),
            {"f": farmer_id},
        ).mappings().first()
    return dict(row) if row else None


@router.post("/swine/reports", status_code=201)
def create_report(body: SwineReportIn):
    # TODO: take the role/user from the staff login instead of trusting the client.
    status = "verified" if body.reported_by_role == "staff" else "submitted"
    try:
        with engine.begin() as conn:
            if not conn.execute(
                text("SELECT 1 FROM tblfarmerregistry WHERE id = :f"), {"f": body.farmer_id}
            ).first():
                raise HTTPException(404, "Farmer not found.")
            if conn.execute(
                text("SELECT 1 FROM tblswinereport WHERE farmer_id = :f AND period_end = :d"),
                {"f": body.farmer_id, "d": body.period_end},
            ).first():
                raise HTTPException(409, "A report for that date already exists for this farmer.")
            check_movements(conn, body.farmer_id, body)
            report_id = insert_report(
                conn, farmer_id=body.farmer_id, body=body, status=status,
                role=body.reported_by_role, user=body.reported_by_user,
            )
            if status == "verified":
                sync_registry_total(conn, body.farmer_id)
    except IntegrityError:
        raise HTTPException(409, "A report for that date already exists for this farmer.")
    return {"report_id": report_id, "status": status}


@router.get("/swine/reports")
def list_reports(status: Optional[str] = None):
    if status not in (None, "", "submitted", "returned", "verified"):
        raise HTTPException(400, "Invalid status.")
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT r.id, r.farmer_id, f.farmer_name, f.municipality, f.barangay,
                       r.period_type, r.period_end, r.status,
                       r.reported_by_role, r.reported_by_user, r.review_note,
                       v.opening, v.closing, v.total_in, v.total_out, v.variance
                FROM tblswinereport r
                JOIN tblfarmerregistry f ON f.id = r.farmer_id
                LEFT JOIN vw_swine_reconciliation v ON v.report_id = r.id
                WHERE (CAST(:status AS text) IS NULL OR r.status = CAST(:status AS text))
                ORDER BY r.period_end DESC, r.id DESC
                LIMIT 500
            """),
            {"status": status or None},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/swine/reports/{report_id}")
def report_detail(report_id: int):
    with engine.connect() as conn:
        rep = conn.execute(
            text("""
                SELECT r.remarks, r.review_note, p.swine_population,
                       p.boar, p.sow, p.gilts, p.piglets, p.grower_fattener
                FROM tblswinereport r
                JOIN tblswinepopulation p ON p.report_id = r.id
                WHERE r.id = :id
            """),
            {"id": report_id},
        ).mappings().first()
        if not rep:
            raise HTTPException(404, "Report not found.")
        movements = conn.execute(
            text("SELECT movement_type, category, quantity FROM tblswinemovement WHERE report_id = :id ORDER BY id"),
            {"id": report_id},
        ).mappings().all()
    out = dict(rep)
    out["report_mode"] = "category" if sum(out[c] or 0 for c in CATS) > 0 else "total"
    out["movements"] = [dict(m) for m in movements]
    return out


class ReviewIn(BaseModel):
    reviewer: str = "staff"
    note: Optional[str] = None


def _get_for_review(conn, report_id: int):
    row = conn.execute(
        text("SELECT farmer_id, status FROM tblswinereport WHERE id = :id FOR UPDATE"),
        {"id": report_id},
    ).first()
    if not row:
        raise HTTPException(404, "Report not found.")
    if row.status != "submitted":
        raise HTTPException(400, "Only reports waiting for review can be verified or returned.")
    return row


@router.patch("/swine/reports/{report_id}/verify")
def verify_report(report_id: int, body: ReviewIn):
    with engine.begin() as conn:
        row = _get_for_review(conn, report_id)
        conn.execute(
            text("""
                UPDATE tblswinereport
                SET status = 'verified', verified_by = :u, verified_at = now(), review_note = NULL
                WHERE id = :id
            """),
            {"u": body.reviewer, "id": report_id},
        )
        sync_registry_total(conn, row.farmer_id)
    return {"report_id": report_id, "status": "verified"}


@router.patch("/swine/reports/{report_id}/return")
def return_report(report_id: int, body: ReviewIn):
    if not body.note or not body.note.strip():
        raise HTTPException(400, "Tell the reporter what to fix.")
    with engine.begin() as conn:
        _get_for_review(conn, report_id)
        conn.execute(
            text("UPDATE tblswinereport SET status = 'returned', review_note = :n WHERE id = :id"),
            {"n": body.note.strip(), "id": report_id},
        )
    return {"report_id": report_id, "status": "returned"}


@router.get("/swine/inventory")
def inventory(municipality: Optional[str] = None):
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT l.farmer_id, f.farmer_name, f.barangay, f.municipality, l.period_end,
                       l.swine_population, l.boar, l.sow, l.gilts, l.piglets,
                       l.grower_fattener, l.unclassified
                FROM vw_swine_latest l
                JOIN tblfarmerregistry f ON f.id = l.farmer_id
                WHERE (CAST(:m AS text) IS NULL OR f.municipality = CAST(:m AS text))
                ORDER BY f.municipality, f.barangay, f.farmer_name
            """),
            {"m": municipality or None},
        ).mappings().all()
    data = [dict(r) for r in rows]
    totals = {k: sum(r[k] or 0 for r in data)
              for k in ("swine_population", "unclassified", *CATS)}
    totals["farmers"] = len(data)
    return {"rows": data, "totals": totals}