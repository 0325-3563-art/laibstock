import os
from fastapi import APIRouter, Query
from sqlalchemy import create_engine, text

router = APIRouter()

# Own engine, so this file never imports from main.py (avoids a circular import)
engine = create_engine(os.environ["ASF_DATABASE_URL"], pool_pre_ping=True)


@router.get("/farmers/search")
def search_farmers(
    municipality: str = Query(..., min_length=1),
    barangay: str | None = Query(None),
):
    sql = """
        SELECT id AS farmer_id,
               date_uploaded,
               farmer_name,
               municipality,
               barangay,
               latitude,
               longitude,
               contact_number,
               type_of_farm,
               total_farm_population,
               rsba_registered,
               rsba_control_number,
               biosecurity_level1_compliant,
               farm_density,
               nearest_farm_km,
               cluster_id
        FROM tblfarmerregistry
        WHERE LOWER(TRIM(municipality)) = LOWER(TRIM(:municipality))
    """
    params = {"municipality": municipality}

    if barangay and barangay.strip():
        sql += " AND LOWER(TRIM(barangay)) = LOWER(TRIM(:barangay))"
        params["barangay"] = barangay

    sql += " ORDER BY barangay, farmer_name"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]