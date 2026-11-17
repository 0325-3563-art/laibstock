from fastapi import FastAPI, UploadFile, File, Query, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
import io, math, os, json
from sqlalchemy import create_engine, text
from datetime import datetime,date
import numpy as np
from functools import lru_cache
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree
from pydantic import BaseModel
import joblib
from shapely.geometry import Point
from trainModel import (load_data, predict_risk, load_artifact,
                        MIN_POSITIVE_FARMS, MIN_SNAPSHOTS)
from mao_login import router as mao_login_router
import gisMap 
import logging
import argparse
import threading
import time
from datetime import datetime
import trainModel
from farmer_livestock import router as farmer_livestock_router
from searchfarmer import router as farmer_search_router
from swine_reports import router as swine_reports_router

try:
    import geopandas as gpd
except ImportError:
    gpd = None

log = logging.getLogger("upload_excel")

app = FastAPI()
app.include_router(mao_login_router)
app.include_router(farmer_livestock_router)
app.include_router(farmer_search_router)
app.include_router(swine_reports_router)


origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      # explicit origins (a wildcard cannot be combined with credentials)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- OPTIONS handler for preflight ---
@app.options("/provinces")
async def options_provinces(request: Request):
    return Response(status_code=200)

DATABASE_URL = os.environ["ASF_DATABASE_URL"]   # set in your environment / .env, never in code
engine = create_engine(DATABASE_URL)


ENGINE = create_engine(os.environ["ASF_DATABASE_URL"], pool_pre_ping=True)
_ARGS = argparse.Namespace(no_db=False, farms=None, cases=None, env=None, db_url=None)


CACHE_TTL_S = 10
_cache = {"t": 0.0, "payload": None}
_lock = threading.Lock()
 

# --- Helpers ---
def clean_dict(d: dict):
    return {k: (None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v) for k, v in d.items()}

def safe_float(val):
    try:
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return None
        return float(val)
    except:
        return None

def safe_int(val, default=0):
    try:
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return default
        return int(val)
    except:
        return default

def clean_contact(val):
    if val is None or str(val).strip() == "":
        return None
    try:
        if isinstance(val, float):
            return str(int(val))
        return str(val).strip()
    except:
        return None

def haversine(coord1, coord2):
    R = 6371  # km
    lat1, lon1 = map(math.radians, coord1)
    lat2, lon2 = map(math.radians, coord2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# --- Endpoints ---

@app.get("/farmers")
def get_farmers():
    with engine.connect() as conn:
        result = conn.execute(text("""
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
            FROM tblFarmerRegistry
        """))
        farmers = result.mappings().all()
        return [dict(row) for row in farmers]

# from fastapi import FastAPI, Query
import requests

# app = FastAPI()
# from fastapi import FastAPI


# app = FastAPI()

# Input schema
    
class DiseaseReport(BaseModel):
     farmer_id: int
     technician_name: str
     disease: str
     status: str
     date_reported: date
     lab_result_date: date | None = None
     remarks: str | None = None
     municipality: str


@app.post("/disease-reports")
def create_disease_report(report: DiseaseReport):
    with engine.begin() as conn:  # use begin() para auto-commit
        farmer = conn.execute(text("""
            SELECT id AS farm_id, latitude, longitude
            FROM tblFarmerRegistry
            WHERE id = :farmer_id
        """), {"farmer_id": report.farmer_id}).mappings().first()

        if not farmer:
            return {"error": "Farmer not found"}

        query = """
            INSERT INTO tbldiseasereports (
                farm_id, technician_name, disease, status,
                date_reported, lab_result_date, remarks,
                report_date, latitude, longitude, is_ground_zero,
                created_at, updated_at, created_by
            )
            VALUES (
                :farm_id, :technician_name, :disease, :status,
                :date_reported, :lab_result_date, :remarks,
                NOW(), :latitude, :longitude,
                :is_ground_zero,
                NOW(), NOW(), :created_by
            )
            RETURNING report_id
        """

        params = {
            "farm_id": farmer["farm_id"],
            "technician_name": report.technician_name,
            "disease": report.disease,
            "status": report.status,
            "date_reported": report.date_reported,
            "lab_result_date": report.lab_result_date,
            "remarks": report.remarks,
            "latitude": farmer["latitude"],
            "longitude": farmer["longitude"],
            "is_ground_zero": True if report.status.lower() == "positive" else False,
            "created_by": report.technician_name
        }

        result = conn.execute(text(query), params)
        new_id = result.scalar_one()

    return {"report_id": new_id, "message": "Disease report saved successfully"}


# ======================================================================
# ML risk: rule-based until enough confirmed ASF cases exist, then supervised.
# The mode is decided in trainModel.py (run it again after new cases are logged).
# Periods are "as of" views: risk at the END of the chosen period, using only
# cases reported on or before that date.
# ======================================================================
def _period_bounds(period_type: str, value: str):
    """Return (start, end) timestamps of the requested period."""
    try:
        if period_type == "month":
            p = pd.Period(value[:7], "M")
            start, end = p.start_time, p.end_time
        elif period_type == "quarter":                      # e.g. 2026Q3
            p = pd.Period(value, "Q")
            start, end = p.start_time, p.end_time
        elif period_type == "semi_annual":                  # e.g. 2026-S2
            year, half = value.split("-S")
            if half not in ("1", "2"):
                raise ValueError
            y = int(year)
            start = pd.Timestamp(y, 1 if half == "1" else 7, 1)
            end = pd.Timestamp(y, 6, 30) if half == "1" else pd.Timestamp(y, 12, 31)
        elif period_type == "year":                         # e.g. 2026
            y = int(value)
            start, end = pd.Timestamp(y, 1, 1), pd.Timestamp(y, 12, 31)
        else:
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {period_type} value: {value}")
    return start.normalize(), end.normalize()


def _risk_response(start: pd.Timestamp, as_of: pd.Timestamp):
    as_of = min(as_of, pd.Timestamp.today().normalize())   # never look past today
    farms, cases = load_data(engine)
    result = predict_risk(farms, cases, as_of=as_of)
    result["risk_score"] = result["risk_score"].round(1)
    # farms whose FIRST confirmed case falls inside the selected period
    in_period = cases[(cases["onset"] >= start) & (cases["onset"] <= as_of)]
    result["new_case_in_period"] = result["id"].isin(in_period["farm_id"]).astype(int)
    cols = ["id", "municipality", "barangay", "latitude", "longitude",
            "risk_level", "risk_score", "zoning", "confirmed_positive",
            "new_case_in_period", "method"]
    return json.loads(result[cols].to_json(orient="records"))   # NaN -> null


@app.get("/ml-risk/status")
def ml_risk_status():
    _, cases = load_data(engine)
    artifact = load_artifact()
    return {
        "mode": artifact["mode"],
        "positive_farms": int(cases["farm_id"].nunique()),
        "positive_months": int(cases["onset"].dt.to_period("M").nunique()),
        "min_positive_farms_for_model": MIN_POSITIVE_FARMS,
        "min_months_for_model": MIN_SNAPSHOTS,
    }


@app.get("/ml-risk/case-counts")
def ml_case_counts():
    """Per month:
      positive_reports / cumulative_reports = every positive report (cases, repeats included)
      new_cases / cumulative                = farms whose FIRST positive report is in that month"""
    _, cases = load_data(engine)
    reports = pd.read_sql(
        """
        SELECT COALESCE(lab_result_date, date_reported) AS d
        FROM tbldiseasereports
        WHERE LOWER(status) = 'positive'
          AND COALESCE(lab_result_date, date_reported) IS NOT NULL
        """, engine)
    if cases.empty and reports.empty:
        return []
    reports["d"] = pd.to_datetime(reports["d"])
    first = min(cases["onset"].min(), reports["d"].min())
    last = max(pd.Timestamp.today().normalize(), cases["onset"].max(), reports["d"].max())
    months = pd.period_range(first, last, freq="M")
    new = cases.groupby(cases["onset"].dt.to_period("M")).size().reindex(months, fill_value=0)
    reps = reports.groupby(reports["d"].dt.to_period("M")).size().reindex(months, fill_value=0)
    return [
        {"month": str(m), "new_cases": int(n), "cumulative": int(c),
         "positive_reports": int(r), "cumulative_reports": int(cr)}
        for m, n, c, r, cr in zip(months, new, new.cumsum(), reps, reps.cumsum())
    ]


@app.get("/ml-risk/periods")
def list_periods():
    _, cases = load_data(engine)
    today = pd.Timestamp.today().normalize()
    start = cases["onset"].min() if not cases.empty else today
    months = pd.period_range(start, today, freq="M")
    return {
        "months": [str(p) for p in months],
        "quarters": sorted({f"{p.year}Q{p.quarter}" for p in months}),
        "semi_annual": sorted({f"{p.year}-S{1 if p.month <= 6 else 2}" for p in months}),
        "years": sorted({str(p.year) for p in months}),
    }


# Date-range view used by the "Annual / Date range" option: risk as of end_date
@app.get("/ml-risk/summary/year")
def ml_risk_summary_range(start_date: date, end_date: date):
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must not be before start_date")
    return _risk_response(pd.Timestamp(start_date), pd.Timestamp(end_date))


@app.get("/ml-risk/summary/{period_type}/{period_value}")
def ml_risk_summary(period_type: str, period_value: str):
    start, end = _period_bounds(period_type, period_value)
    return _risk_response(start, end)



#@app.post("/ml-risk/{period_type}/{period_value}")
# def ml_risk(period_type: str, period_value: str, data: FarmData):
#     X_new = pd.DataFrame([{
#         "farm_density": data.farm_density,
#         "total_farm_population": data.total_farm_population,
#         "nearest_ground_zero_km": data.nearest_ground_zero_km,
#         "biosecurity_level1_compliant": int(data.biosecurity_level1_compliant),
#         "cluster_id": data.cluster_id
#     }])

#     # Select correct model dictionary
#     if period_type == "month":
#         model = monthly_models.get(period_value)
#     elif period_type == "quarter":
#         model = quarterly_models.get(period_value)
#     elif period_type == "semi_annual":
#         model = semiannual_models.get(period_value)
#     elif period_type == "year":
#         model = annual_models.get(period_value)
#     else:
#         return {"error": "Invalid period type"}

#     if not model:
#         return {"error": f"No model found for {period_value}"}

#     predicted_risk = model.predict(X_new)[0]
#     return {"risk_level": predicted_risk}
# @app.post("/ml-risk/year")
# def ml_risk_year(
#     start_date: str = Query(..., description="Start date in YYYY-MM-DD"),
#     end_date: str = Query(..., description="End date in YYYY-MM-DD"),
#     data: FarmData = None
# ):
#     # Convert to datetime
#     start_dt = datetime.strptime(start_date, "%Y-%m-%d")
#     end_dt = datetime.strptime(end_date, "%Y-%m-%d")

#     X_new = pd.DataFrame([{
#         "farm_density": data.farm_density,
#         "total_farm_population": data.total_farm_population,
#         "nearest_ground_zero_km": data.nearest_ground_zero_km,
#         "biosecurity_level1_compliant": int(data.biosecurity_level1_compliant),
#         "cluster_id": data.cluster_id
#     }])

#     # Pick annual model (you can decide logic: by year or custom)
#     model = None
#     for year_key, annual_model in annual_models.items():
#         if str(start_dt.year) == year_key:
#             model = annual_model
#             break

#     if not model:
#         return {"error": f"No annual model found for {start_dt.year}"}

#     predicted_risk = model.predict(X_new)[0]
#     return {"risk_level": predicted_risk}


@app.get("/provinces")
def get_provinces():
    try:
        url = "https://psgc.gitlab.io/api/provinces/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        provinces = response.json()
        return {"provinces": [{"code": p["code"], "name": p["name"]} for p in provinces]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/municipalities")
def get_municipalities(province_code: str = Query(...)):
    try:
        url = "https://psgc.gitlab.io/api/cities-municipalities/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        municipalities = response.json()
        filtered = [m for m in municipalities if m["provinceCode"] == province_code]
        return {"municipalities": [{"code": m["code"], "name": m["name"]} for m in filtered]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/barangays")
def get_barangays(municipality_code: str = Query(...)):
    try:
        url = "https://psgc.gitlab.io/api/barangays/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        barangays = response.json()
        filtered = [b for b in barangays if b["municipalityCode"] == municipality_code]
        return {"barangays": [{"code": b["code"], "name": b["name"]} for b in filtered]}
    except Exception as e:
        return {"error": str(e)}
    
@app.get("/quezon/municipalities")
def get_quezon_municipalities():
    try:
        url = "https://psgc.gitlab.io/api/cities-municipalities/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        municipalities = response.json()
        # Filter Quezon Province only
        filtered = [
            m for m in municipalities
            if m["provinceCode"] == "045600000" and m["isMunicipality"]
        ]
        return {"municipalities": [{"code": m["code"], "name": m["name"]} for m in filtered]}
    except Exception as e:
        return {"error": str(e)}

    
                    
@app.get("/quezon/barangays")
def get_barangays(municipality_code: str = Query(...)):
    try:
        url = "https://psgc.gitlab.io/api/barangays/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        barangays = response.json()
        # Filter barangays by municipalityCode
        filtered = [b for b in barangays if b["municipalityCode"] == municipality_code]
        return {"barangays": [{"code": b["code"], "name": b["name"]} for b in filtered]}
    except Exception as e:
        return {"error": str(e)}    
    
@app.get("/swine/population")
def get_swine_population(
    municipality: str = Query(...),
    level: str = Query("municipality")  # "municipality" or "barangay"
):
    with engine.connect() as conn:
        if level == "municipality":
            # Total swine for the selected municipality
            query = text("""
                SELECT SUM(total_farm_population) AS total
                FROM tblfarmerregistry
                WHERE municipality = :municipality
            """)
            result = conn.execute(query, {"municipality": municipality}).fetchone()
            return {
                "level": "municipality",
                "municipality": municipality,
                "total_swine": result[0] or 0
            }

        elif level == "barangay":
            # Totals per barangay under the selected municipality
            query = text("""
                SELECT barangay, SUM(total_farm_population) AS total
                FROM tblfarmerregistry
                WHERE municipality = :municipality
                GROUP BY  barangay
                ORDER BY barangay ASC
            """)
            rows = conn.execute(query, {"municipality": municipality}).fetchall()
            return {
                "level": "barangay",
                "municipality": municipality,
                "barangays": [
                    {"name": r[0], "total_swine": r[1]} for r in rows
                ]
            }
@app.get("/dashboard/registered_farms")
def get_registered_farms():
    with engine.connect() as conn:
        query = text("SELECT COUNT(*) FROM tblfarmerregistry")
        result = conn.execute(query).scalar()
        return {"registered_farms": result}
    
@app.get("/dashboard/total_animals")
def get_total_animals():
    with engine.connect() as conn:
        query = text("SELECT SUM(total_farm_population) FROM tblfarmerregistry")
        result = conn.execute(query).scalar()
        return {"total_animals": result or 0}

@app.get("/dashboard/reports_this_month")
def get_reports_this_month():
    today = datetime.today()
    first_day = today.replace(day=1)
    # compute next month start
    if today.month == 12:
                next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
                next_month = today.replace(month=today.month + 1, day=1)
    

    with engine.connect() as conn:
        query = text("""
            SELECT COUNT(*) 
            FROM tbldiseasereports
            WHERE date_reported >= :first_day
              AND date_reported < :next_month
        """)
        
        result = conn.execute(query, {
            "first_day": first_day,
            "next_month": next_month
        }).scalar()

        return {"reports_this_month": result or 0}

@app.get("/dashboard/active_outbreaks")
def get_active_outbreaks():
    with engine.connect() as conn:
        query = text("""
            SELECT fr.municipality,
                   COUNT(*) AS positive_cases,
                   MAX(dr.report_date) AS latest_report
            FROM tbldiseasereports dr
            JOIN tblfarmerregistry fr ON dr.farm_id = fr.id
            WHERE dr.disease = 'ASF' AND dr.status = 'Positive'
            GROUP BY fr.municipality
            HAVING COUNT(*) >= 2
        """)
        result = conn.execute(query).fetchall()

        return [
            {
                "municipality": row[0],
                "positive_cases": row[1],
                "latest_report": row[2].strftime("%Y-%m-%d %H:%M:%S") if row[2] else None,
                "outbreak": True   # always true since HAVING ensures >=2 positives
            }
            for row in result
        ]

# --- NEW endpoint: filtered farmers ---
@app.get("/farmers/filter")
def get_filtered_farmers(
    province: str = Query(...),
    municipality: str = Query(...),
    barangay: str = Query(...)
):
    # Step 1: Convert codes to names using PSGC API
    prov_name = requests.get(f"https://psgc.gitlab.io/api/provinces/{province}").json()["name"]
    mun_name = requests.get(f"https://psgc.gitlab.io/api/cities-municipalities/{municipality}").json()["name"]
    brgy_name = requests.get(f"https://psgc.gitlab.io/api/barangays/{barangay}").json()["name"]

    # Step 2: Query DB using names
    query = """
        SELECT id AS farmer_id,
               farmer_name
        FROM tblfarmerregistry
        WHERE province = :province
          AND municipality = :municipality
          AND barangay = :barangay
        ORDER BY farmer_name ASC
    """
    with engine.connect() as conn:
        result = conn.execute(text(query), {
            "province": prov_name,
            "municipality": mun_name,
            "barangay": brgy_name
        })
        farmers = result.mappings().all()
        return [dict(row) for row in farmers]      



#------------------------------------------------------------------ settings
COLUMN_MAP = {
    "Name of Farmer": "farmer_name",
    "Municipality": "municipality",
    "Barangay": "barangay",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Contact No.": "contact_number",
    "Type of farm": "type_of_farm",
    "Total Farm Population": "total_farm_population",
    "RSBSA Registered Y/N": "rsba_registered",
    "RSBSA Control No.": "rsba_control_number",
    "Compliant to Biosecurity Level (0,1,2)": "biosecurity_level1_compliant",
}
REQUIRED = ("farmer_name", "municipality", "barangay")
 
# Opening-balance report given to every farmer, dated the day before the first
# reporting period. Move these to config if the period changes.
BASELINE_START = date(2026, 9, 1)
BASELINE_END = date(2026, 9, 30)
 
METRIC_CRS = "EPSG:3857"      # same as before; EPSG:32651 (UTM 51N) is more accurate for Quezon
ROAD_ACCESS_M = 1000          # "road nearby" = within 1 km (the old comment said 2 km, the code used 1 km)
EARTH_RADIUS_KM = 6371.0088
TRUE_VALUES = {"Y", "YES", "1", "TRUE"}
COMMERCIAL = {"SC", "CM", "COMMERCIAL", "C", "COM"}
BACKYARD = {"BY", "BACKYARD", "B", "BYD"}
 
 
# ------------------------------------------------------------------ small helpers
def _text(v):
    """Clean cell -> stripped string or None (NaN, blanks and floats like 123.0 handled)."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None
 
 
def _float(v):
    return None if v is None or pd.isna(v) else float(v)
 
 
def _truthy(v):
    s = _text(v)
    return s is not None and s.upper() in TRUE_VALUES
 
 
def _farm_type(v):
    s = (_text(v) or "").upper()
    if s in COMMERCIAL:
        return "Small Commercial"
    if s in BACKYARD:
        return "Backyard"
    return "Unknown"
 
 
# ------------------------------------------------------------------ geo data (loaded once)
@lru_cache(maxsize=1)
def load_geo():
    """Returns ({barangay: area_km2}, roads_geometry_or_None). Cached; restart to reload files."""
    areas, roads_union = {}, None
    if gpd is None:
        return areas, roads_union
 
    if os.path.exists("barangays.shp"):
        b = gpd.read_file("barangays.shp").to_crs(METRIC_CRS)
        if "barangay" in b.columns:
            b["area_km2"] = b.geometry.area / 1e6
            areas = b.groupby(b["barangay"].astype(str).str.strip())["area_km2"].first().to_dict()
 
    roads_file = "hotosm_phl_roads_lines_geojson.geojson"
    quezon_file = "ShapeFiles/QuezonMunicipalities-Barangays.shp"
    if os.path.exists(roads_file) and os.path.exists(quezon_file):
        roads = gpd.read_file(roads_file).to_crs(METRIC_CRS)
        roads = roads[roads["highway"].isin(["primary", "secondary", "tertiary"])]
        quezon = gpd.read_file(quezon_file).to_crs(METRIC_CRS)
        roads = gpd.overlay(roads, quezon, how="intersection")
        if not roads.empty:
            g = roads.geometry
            roads_union = g.union_all() if hasattr(g, "union_all") else g.unary_union
    return areas, roads_union
 
 
def add_geo_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised replacement for the per-row loops (was O(n^2) with iterrows inside iterrows)."""
    areas, roads_union = load_geo()
    has = df["latitude"].notna() & df["longitude"].notna()
 
    # Cluster (-1 = noise or no coordinates)
    df["cluster_id"] = -1
    if has.any():
        rad = np.radians(df.loc[has, ["latitude", "longitude"]].to_numpy(dtype=float))
        df.loc[has, "cluster_id"] = DBSCAN(
            eps=5 / 6371, min_samples=2, metric="haversine"
        ).fit(rad).labels_
 
    # Nearest other farm (km). Same rule as before: farms at identical coordinates are ignored.
    df["nearest_farm_km"] = np.nan
    if has.sum() >= 2:
        pts = df.loc[has, ["latitude", "longitude"]].to_numpy(dtype=float)
        uniq, inverse = np.unique(pts, axis=0, return_inverse=True)
        inverse = np.asarray(inverse).reshape(-1)
        if len(uniq) >= 2:
            dist, _ = BallTree(np.radians(uniq), metric="haversine").query(np.radians(uniq), k=2)
            df.loc[has, "nearest_farm_km"] = (dist[:, 1] * EARTH_RADIUS_KM)[inverse]
 
    # Farm density: farms in the barangay / barangay area, or the farm count if the area is unknown
    counts = df["barangay"].map(df["barangay"].value_counts())
    df["farm_density"] = [
        (c / areas[b]) if areas.get(b, 0) > 0 else c for b, c in zip(df["barangay"], counts)
    ]
 
    # Nearest major road
    df["nearest_road_km"] = 0.0
    df["access_road_nearby"] = False
    if roads_union is not None and has.any():
        pts = gpd.GeoSeries(
            gpd.points_from_xy(df.loc[has, "longitude"], df.loc[has, "latitude"]),
            index=df.index[has], crs="EPSG:4326",
        ).to_crs(METRIC_CRS)
        metres = pts.distance(roads_union)
        df.loc[has, "nearest_road_km"] = metres / 1000
        df.loc[has, "access_road_nearby"] = metres <= ROAD_ACCESS_M
    return df
 
 
# ------------------------------------------------------------------ database helpers
def ensure_baseline(conn, farmer_id: int, total: int) -> bool:
    """Give the farmer a verified opening-balance report with a linked population row, once.
    Returns True if it created one."""
    if conn.execute(
        text("SELECT 1 FROM tblswinereport WHERE farmer_id = :f AND status = 'verified' LIMIT 1"),
        {"f": farmer_id},
    ).first():
        return False
    report_id = conn.execute(text("""
        INSERT INTO tblswinereport
            (farmer_id, period_type, period_start, period_end, status,
             reported_by_role, reported_by_user, verified_by, verified_at, remarks)
        VALUES (:f, 'monthly', :s, :e, 'verified',
                'staff', 'excel-upload', 'excel-upload', now(),
                'Opening balance from Excel upload')
        RETURNING id
    """), {"f": farmer_id, "s": BASELINE_START, "e": BASELINE_END}).scalar_one()
    conn.execute(text("""
        INSERT INTO tblswinepopulation
            (farmer_id, dateadded, swine_population, boar, sow, gilts, piglets, grower_fattener, report_id)
        VALUES (:f, :d, :total, 0, 0, 0, 0, 0, :r)
    """), {"f": farmer_id, "d": BASELINE_END, "total": total, "r": report_id})
    return True
 
 
INSERT_FARMER = text("""
    INSERT INTO tblfarmerregistry (
        date_uploaded, farmer_name, municipality, barangay, latitude, longitude,
        contact_number, type_of_farm, total_farm_population,
        rsba_registered, rsba_control_number, biosecurity_level1_compliant,
        farm_density, nearest_farm_km, cluster_id, nearest_road_km, access_road_nearby
    ) VALUES (
        :upload_time, :farmer_name, :municipality, :barangay, :latitude, :longitude,
        :contact_number, :type_of_farm, :total_farm_population,
        :rsba_registered, :rsba_control_number, :biosecurity_level1_compliant,
        :farm_density, :nearest_farm_km, :cluster_id, :nearest_road_km, :access_road_nearby
    ) RETURNING id
""")
 
FIND_FARMER = text("""
    SELECT id, total_farm_population FROM tblfarmerregistry
    WHERE LOWER(TRIM(farmer_name)) = LOWER(:farmer_name)
      AND LOWER(TRIM(municipality)) = LOWER(:municipality)
      AND LOWER(TRIM(barangay)) = LOWER(:barangay)
    ORDER BY id LIMIT 1
""")
 
 
# ------------------------------------------------------------------ route
@app.post("/upload-excel")
def upload_excel(file: UploadFile = File(...)):
    # Plain `def` (not async): the heavy pandas/geo work runs in FastAPI's thread pool
    # instead of blocking the event loop for every other request.
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(400, "Please upload an Excel file (.xlsx, .xlsm or .xls).")
    try:
        xls = pd.ExcelFile(io.BytesIO(file.file.read()))
    except Exception as e:
        raise HTTPException(400, f"Could not read the Excel file: {e}")
 
    created, existing, failed, warnings = [], [], [], []
    baselines = 0
    upload_time = datetime.now()
 
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        df.columns = df.columns.astype(str).str.strip()
        df = df.rename(columns=COLUMN_MAP).dropna(how="all")
 
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            warnings.append(f"Sheet '{sheet}' skipped: missing column(s) {', '.join(missing)}.")
            continue
        if df.empty:
            continue
        for col in COLUMN_MAP.values():
            if col not in df.columns:
                df[col] = None
 
        # Clean text columns, then fill missing coordinates from the first farm in the same barangay
        for col in REQUIRED:
            df[col] = df[col].map(_text)
        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
        first = (df.dropna(subset=["latitude", "longitude"])
                   .groupby("barangay")[["latitude", "longitude"]].first())
        df["latitude"] = df["latitude"].fillna(df["barangay"].map(first["latitude"]))
        df["longitude"] = df["longitude"].fillna(df["barangay"].map(first["longitude"]))
 
        df = add_geo_features(df)
 
        for idx, row in df.iterrows():
            excel_row = int(idx) + 2          # +1 for 0-based index, +1 for the header row
            rec = {
                "upload_time": upload_time,
                "farmer_name": row["farmer_name"],
                "municipality": row["municipality"],
                "barangay": row["barangay"],
                "latitude": _float(row["latitude"]),
                "longitude": _float(row["longitude"]),
                "contact_number": clean_contact(row["contact_number"]),
                "type_of_farm": _farm_type(row["type_of_farm"]),
                "total_farm_population": safe_int(row["total_farm_population"], 0),
                "rsba_registered": _truthy(row["rsba_registered"]),
                "rsba_control_number": _text(row["rsba_control_number"]),
                "biosecurity_level1_compliant": _truthy(row["biosecurity_level1_compliant"]),
                "farm_density": _float(row["farm_density"]),
                "nearest_farm_km": _float(row["nearest_farm_km"]),
                "cluster_id": int(row["cluster_id"]),
                "nearest_road_km": _float(row["nearest_road_km"]),
                "access_road_nearby": bool(row["access_road_nearby"]),
            }
            shown = {k: v for k, v in rec.items() if k != "upload_time"}
 
            blank = [c for c in REQUIRED if not rec[c]]
            if blank:
                failed.append({"sheet": sheet, "excel_row": excel_row, "row": clean_dict(shown),
                               "reason": f"Missing {', '.join(blank)}."})
                continue
 
            try:
                # One transaction per row: a bad row rolls back only itself.
                with engine.begin() as conn:
                    found = conn.execute(FIND_FARMER, rec).first()
                    if found:
                        farmer_id, registry_total = found
                        # Existing farmer: the count already in the registry is the opening balance.
                        total = registry_total if registry_total is not None else rec["total_farm_population"]
                        is_new = False
                    else:
                        farmer_id = conn.execute(INSERT_FARMER, rec).scalar_one()
                        total = rec["total_farm_population"]
                        is_new = True
                    # Runs for new AND existing farmers; does nothing if a verified count exists.
                    if ensure_baseline(conn, farmer_id, total or 0):
                        baselines += 1
                (created if is_new else existing).append(
                    clean_dict({**shown, "farmer_id": farmer_id}))
            except Exception as e:
                log.exception("Insert failed for %s row %s", sheet, excel_row)
                failed.append({"sheet": sheet, "excel_row": excel_row, "row": clean_dict(shown),
                               "reason": f"DB insert error: {e}"})
 
    return {
        "farmers": created,        # newly added farmers (same meaning as before)
        "existing": existing,      # farmers that were already registered
        "failed": failed,
        "warnings": warnings,
        "summary": {
            "created": len(created),
            "existing": len(existing),
            "failed": len(failed),
            "baseline_reports_added": baselines,
        },
    }
@app.post("/add-farmer")
async def add_farmer(request: Request):
    formData = await request.json()

    # --- Compute total population ---
    if formData.get("entryMode") == "breakdown":
        total = (
            int(formData.get("boar", 0)) +
            int(formData.get("sow", 0)) +
            int(formData.get("gilts", 0)) +
            int(formData.get("piglets", 0)) +
            int(formData.get("grower_fattener", 0))
        )
    else:
        total = int(formData.get("total_farm_population", 0))

    # --- Database transaction ---
    with engine.begin() as conn:
        # --- Get existing coordinates ---
        existing_coords = conn.execute(text("""
            SELECT latitude, longitude FROM tblfarmerregistry
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """)).fetchall()

        coords = [
            (safe_float(row[0]), safe_float(row[1]))
            for row in existing_coords
            if row[0] is not None and row[1] is not None
        ]
        coords.append((float(formData["latitude"]), float(formData["longitude"])))

        # --- DBSCAN clustering ---
        cluster_id = -1
        if len(coords) > 1:
            coords_rad = np.radians(coords)
            db = DBSCAN(eps=5/6371, min_samples=2, metric='haversine').fit(coords_rad)
            labels = db.labels_
            cluster_id = int(labels[-1])

        # --- Nearest farm distance ---
        farm_coords = (safe_float(formData["latitude"]), safe_float(formData["longitude"]))
        nearest_farm_km = min(
            [haversine(farm_coords, coords[i]) for i in range(len(coords)-1)],
            default=None
        )

        # --- Farm density ---
        bname = str(formData.get("barangay")).strip()
        farm_count = conn.execute(text("""
            SELECT COUNT(*) FROM tblFarmerRegistry WHERE barangay = :barangay
        """), {"barangay": bname}).scalar() + 1

        density_val = farm_count
        if gpd is not None and os.path.exists("barangays.shp"):
            barangays = gpd.read_file("barangays.shp").to_crs(epsg=3857)
            barangays["area_km2"] = barangays.geometry.area / 1e6
            if "barangay" in barangays.columns and bname in barangays["barangay"].values:
                area_km2 = float(barangays.loc[barangays["barangay"] == bname, "area_km2"].values[0])
                if area_km2 > 0:
                    density_val = farm_count / area_km2

        # --- Nearest road distance ---
        nearest_road_km, access_road_nearby = 0.0, False
        if gpd is not None and os.path.exists("hotosm_phl_roads_lines_geojson.geojson"):
            roads_gdf = gpd.read_file("hotosm_phl_roads_lines_geojson.geojson").to_crs(epsg=3857)
            roads_gdf = roads_gdf[roads_gdf["highway"].isin(["primary", "secondary", "tertiary"])]
            if os.path.exists("ShapeFiles/QuezonMunicipalities-Barangays.shp"):
                quezon = gpd.read_file("ShapeFiles/QuezonMunicipalities-Barangays.shp").to_crs(epsg=3857)
                roads_gdf = gpd.overlay(roads_gdf, quezon, how="intersection")

            pt = gpd.GeoDataFrame(
                geometry=[Point(formData["longitude"], formData["latitude"])],
                crs="EPSG:4326"
            ).to_crs(epsg=3857)
            nearest_road_m = roads_gdf.distance(pt.geometry.iloc[0]).min()
            nearest_road_km = nearest_road_m / 1000
            access_road_nearby = nearest_road_m <= 1000

        # --- Convert engineered features ---
        nearest_farm_km = float(nearest_farm_km) if nearest_farm_km is not None else None
        nearest_road_km = float(nearest_road_km) if nearest_road_km is not None else None
        access_road_nearby = bool(access_road_nearby)
        cluster_id = int(cluster_id) if cluster_id is not None else -1
        density_val = float(density_val) if density_val is not None else None

        # --- Insert Farmer Registry ---
        farmer_query = text("""
            INSERT INTO tblfarmerregistry (
                date_uploaded, farmer_name, municipality, barangay, province,
                latitude, longitude, contact_number, type_of_farm,
                total_farm_population, rsba_registered, rsba_control_number,
                biosecurity_level1_compliant, farm_density, nearest_farm_km,
                cluster_id, nearest_road_km, access_road_nearby
            )
            VALUES (
                :date_uploaded, :farmer_name, :municipality, :barangay, :province,
                :latitude, :longitude, :contact_number, :type_of_farm,
                :total_farm_population, :rsba_registered, :rsba_control_number,
                :biosecurity_level1_compliant, :farm_density, :nearest_farm_km,
                :cluster_id, :nearest_road_km, :access_road_nearby
            )
            RETURNING id
        """)

        farmer_params = {
            "date_uploaded": datetime.now(),
            "farmer_name": formData["farmer_name"],
            "municipality": formData["municipality"],
            "barangay": formData["barangay"],
            "province": formData.get("province"),
            "latitude": formData.get("latitude"),
            "longitude": formData.get("longitude"),
            "contact_number": formData.get("contact_number"),
            "type_of_farm": formData.get("type_of_farm"),
            "total_farm_population": total,
            "rsba_registered": formData.get("rsba_registered", False),
            "rsba_control_number": formData.get("rsba_control_number"),
            "biosecurity_level1_compliant": formData.get("biosecurity_level", "0"),
            "farm_density": density_val,
            "nearest_farm_km": nearest_farm_km,
            "cluster_id": cluster_id,
            "nearest_road_km": nearest_road_km,
            "access_road_nearby": access_road_nearby
        }

        farmer_id = conn.execute(farmer_query, farmer_params).scalar_one()

        # --- Insert Swine Population ---
        swine_query = text("""
            INSERT INTO tblswinepopulation (
                farmer_id, boar, sow, gilts, piglets, grower_fattener,
                swine_population, dateadded
            )
            VALUES (
                :farmer_id, :boar, :sow, :gilts, :piglets, :grower_fattener,
                :total_swine_population, NOW()
            )
        """)

        swine_params = {
            "farmer_id": farmer_id,
            "boar": formData.get("boar"),
            "sow": formData.get("sow"),
            "gilts": formData.get("gilts"),
            "piglets": formData.get("piglets"),
            "grower_fattener": formData.get("grower_fattener"),
            "total_swine_population": total
        }

        conn.execute(swine_query, swine_params)

    # --- Return response (outside the with block) ---
    #print("Returning success response...")  # debug log
    return JSONResponse(
    status_code=201,
    content={
        "status": "success",
        "message": f"Farmer '{formData['farmer_name']}' has been added successfully.",
        "farmer_id": farmer_id
    }
)

def _compute():
    farms, cases = trainModel.load_data(ENGINE)
    # as_of = NOW (not midnight): a case saved today with a time of day must count immediately.
    # predict_risk() defaults to today's midnight, which would hide it until tomorrow.
    df = trainModel.predict_risk(farms, cases, as_of=pd.Timestamp.now())
 
    recs = gisMap.build_records(
        df,
        gisMap.load_registry(_ARGS, ENGINE),
        gisMap.load_cases(_ARGS, ENGINE),
    )
    positives = [dict(id=r["id"], lat=r["lat"], lon=r["lon"]) for r in recs if r["pos"] and r["ok"]]
    meta = {
        "as_of": datetime.today().strftime("%Y-%m-%d"),
        "method": str(df["method"].iloc[0]) if len(df) else "n/a",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return {"farms": recs, "cases": positives, "meta": meta}

@app.get("/ml-map")
def risk_map(refresh: bool = False):
    with _lock:
        if refresh or _cache["payload"] is None or time.time() - _cache["t"] > CACHE_TTL_S:
            _cache.update(payload=_compute(), t=time.time())
        return _cache["payload"]
 

# @app.get("/ml-map")
# def risk_map():
#     # Load the latest CSV or DB
#     df = pd.read_csv("farm_risk_latest.csv")
#     eng = gisMap.get_engine(argparse.Namespace(
#         no_db=False, farms=None, cases=None, env=None, db_url=None
#     ))
#     recs = gisMap.build_records(df, gisMap.load_registry(argparse.Namespace(farms=None), eng),
#                                 gisMap.load_cases(argparse.Namespace(cases=None), eng))
#     cases = [dict(id=r["id"], lat=r["lat"], lon=r["lon"]) for r in recs if r["pos"] and r["ok"]]
#     meta = {"as_of": datetime.today().strftime("%Y-%m-%d"), "method": "ML model"}

#     return {"farms": recs, "cases": cases, "meta": meta}




# async def add_farmer(request: Request):
#     formData = await request.json()

#     # Compute total depending on mode
#     if formData.get("entryMode") == "breakdown":
#         total = (
#             int(formData.get("boar", 0)) +
#             int(formData.get("sow", 0)) +
#             int(formData.get("gilts", 0)) +
#             int(formData.get("piglets", 0)) +
#             int(formData.get("grower_fattener", 0))
#         )
#     else:
#        total = int(formData["total_farm_population"])




       

#     existing_coords = conn.execute(text("""
#     SELECT latitude, longitude FROM tblfarmerregistry
#     WHERE latitude IS NOT NULL AND longitude IS NOT NULL
# """)).fetchall()

    

#     farm_coords = (formData["latitude"], formData["longitude"])
#     nearest_farm_km = min(
#     [haversine(farm_coords, (row[0], row[1])) for row in existing_coords],
#     default=None
# )

#     with engine.begin() as conn:  # begin() auto-commits
#         # Insert into Farmer Registry
#         farmer_query = text("""
#             INSERT INTO tblfarmerregistry (
#                 date_uploaded, farmer_name, municipality, barangay, province,
#                 latitude, longitude, contact_number, type_of_farm,
#                 total_farm_population, rsba_registered, rsba_control_number,
#                 biosecurity_level1_compliant
#             )
#             VALUES (
#                 :date_uploaded, :farmer_name, :municipality, :barangay, :province,
#                 :latitude, :longitude, :contact_number, :type_of_farm,
#                 :total_farm_population, :rsba_registered, :rsba_control_number,
#                 :biosecurity_level1_compliant
#             )
#             RETURNING id
#         """)

#         farmer_params = {
#             "date_uploaded": datetime.now(),
#             "farmer_name": formData["farmer_name"],
#             "municipality": formData["municipality"],
#             "barangay": formData["barangay"],
#             "province": formData.get("province"),
#             "latitude": formData.get("latitude"),
#             "longitude": formData.get("longitude"),
#             "contact_number": formData.get("contact_number"),
#             "type_of_farm": formData.get("type_of_farm"),
#             "total_farm_population": total,
#             "rsba_registered": formData.get("rsba_registered", False),
#             "rsba_control_number": formData.get("rsba_control_number"),
#             "biosecurity_level1_compliant": formData.get("biosecurity_level", "0")
#         }

#         farmer_id = conn.execute(farmer_query, farmer_params).scalar_one()

#         # Insert into Swine Population
#         swine_query = text("""
#             INSERT INTO tblswinepopulation (
#                 farmer_id, boar, sow, gilts, piglets, grower_fattener,
#                 swine_population, dateadded
#             )
#             VALUES (
#                 :farmer_id, :boar, :sow, :gilts, :piglets, :grower_fattener,
#                 :total_swine_population, NOW()
#             )
#         """)

#         swine_params = {
#             "farmer_id": farmer_id,
#             "boar": formData.get("boar"),
#             "sow": formData.get("sow"),
#             "gilts": formData.get("gilts"),
#             "piglets": formData.get("piglets"),
#             "grower_fattener": formData.get("grower_fattener"),
#             "total_swine_population": total
#         }

#         conn.execute(swine_query, swine_params)

#     return {"message": "Farmer added successfully", "farmer_id": farmer_id}