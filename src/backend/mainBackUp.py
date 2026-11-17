from unittest import result
from fastapi import FastAPI, UploadFile, File, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
import io, math, os
from sqlalchemy import create_engine, text
from datetime import datetime,date
import numpy as np
from sklearn.cluster import DBSCAN
from pydantic import BaseModel
import joblib
from shapely.geometry import Point
from trainModel import zoning_outcome
from mao_login import router as mao_login_router

try:
    import geopandas as gpd
except ImportError:
    gpd = None

app = FastAPI()
app.include_router(mao_login_router)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"] ,  # origins,      # listahan ng allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- OPTIONS handler for preflight ---
@app.options("/provinces")
async def options_provinces(request: Request):
    return Response(status_code=200)

DATABASE_URL = "postgresql+psycopg2://postgres:Asawanid5@localhost:5432/dbLAIBStock"
engine = create_engine(DATABASE_URL)

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

    @app.get("/farmers/filter")
    def get_filtered_farmers(
    province: str = Query(None),
    municipality: str = Query(None),
    barangay: str = Query(None)
):
        query = """
        SELECT id AS farmer_id,
               date_uploaded,
               farmer_name,
               province,
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
        WHERE 1=1
    """
    params = {}

    if province:
        query += " AND province = :province"
        params["province"] = province

    if municipality:
        query += " AND municipality = :municipality"
        params["municipality"] = municipality

    if barangay:
        query += " AND barangay = :barangay"
        params["barangay"] = barangay

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
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


monthly_models = joblib.load("./risk_models_monthly.pkl")
quarterly_models = joblib.load("./risk_models_quarterly.pkl")
semiannual_models = joblib.load("./risk_models_semiannual.pkl")
annual_models = joblib.load("./risk_models_annual.pkl")

class FarmData(BaseModel):
    latitude: float
    longitude: float
    total_farm_population: int
    biosecurity_level1_compliant: bool
    farm_density: float
    nearest_ground_zero_km: float
    cluster_id: int

# ML-risk endpoint
@app.get("/ml-risk/periods")
def list_periods():
    return {
        "months": list(monthly_models.keys()),
        "quarters": list(quarterly_models.keys()),
        "semi_annual": list(semiannual_models.keys()),
        "years": list(annual_models.keys())
    }

@app.get("/ml-risk/summary/{period_type}/{period_value}")
def ml_risk_summary(period_type: str, period_value: str):
    model = None
    # --- Select correct model dictionary ---
    if period_type == "month":
        period_value = period_value[:7]
        model = monthly_models.get(period_value)
    elif period_type == "quarter":
        print("Available quarterly models:", quarterly_models.keys())
        print("Quarter filter value:", period_value)
        model = quarterly_models.get(period_value)
        #df = df[df["lab_result_date"].dt.to_period("Q").astype(str) == period_value]
        
    elif period_type == "semi_annual":
        model = semiannual_models.get(period_value)
    elif period_type == "year":
        model = annual_models.get(period_value)
    else:
        return []

    if not model:
        print("No model found for", period_value)
        return []

    # --- Query farms ---
    query = """
    SELECT f.id,
           f.municipality,
           f.barangay,
           f.latitude,
           f.longitude,
           f.farm_density,
           f.total_farm_population,
           f.biosecurity_level1_compliant,
           f.cluster_id,
           f.nearest_road_km,
           f.access_road_nearby,
           MAX(d.status) AS status,
           MAX(d.lab_result_date) AS lab_result_date
    FROM tblfarmerregistry f
    LEFT JOIN tbldiseasereports d ON f.id = d.farm_id
    GROUP BY f.id, f.municipality, f.barangay,
             f.latitude, f.longitude,
             f.farm_density, f.total_farm_population,
             f.biosecurity_level1_compliant, f.cluster_id,
             f.nearest_road_km, f.access_road_nearby;
    """
    df = pd.read_sql(query, engine).drop_duplicates(subset=["id"])
    #print("After SQL:", len(df))

    # --- Filter by period ---
    df["lab_result_date"] = pd.to_datetime(df["lab_result_date"])
    if period_type == "month":
        df = df[df["lab_result_date"].dt.to_period("M").astype(str) == period_value]
    elif period_type == "quarter":
        df = df[df["lab_result_date"].dt.to_period("Q").astype(str) == period_value]
    elif period_type == "year":
        df = df[df["lab_result_date"].dt.year.astype(str) == period_value]
    elif period_type == "semi_annual":
        df = df[df["lab_result_date"].dt.month.map(lambda m: 1 if m <= 6 else 2).astype(str) == period_value]

    # --- Split sets ---
    mask = df["lab_result_date"].notna()
    df_period = df[mask].copy()
    df_missing = df[~mask].copy()

    # Defaults for missing
    df_missing["asf_positive"] = 0
    df_missing["outbreak_group"] = 0
    df_missing["risk_level"] = "Low"
    df_missing["risk_score"] = 0
    df_missing["zoning"] = "Protected/Surveillance Zone"

    # --- Outbreak group ---
    df_period["asf_positive"] = df_period["status"].apply(lambda s: 1 if s == "Positive" else 0)
    outbreaks = df_period.groupby("municipality")["asf_positive"].sum()
    outbreak_muns = outbreaks[outbreaks >= 2].index
    df_period["outbreak_group"] = df_period["municipality"].apply(lambda m: 1 if m in outbreak_muns else 0)

    # --- Ground zero distances ---
    gz = df_period[df_period["asf_positive"] == 1]
    all_farms_gdf = gpd.GeoDataFrame(
        pd.read_sql('SELECT id, municipality, barangay, latitude, longitude FROM "tblfarmerregistry";', engine),
        geometry=gpd.points_from_xy(
            pd.read_sql('SELECT id, municipality, barangay, latitude, longitude FROM "tblfarmerregistry";', engine)["longitude"],
            pd.read_sql('SELECT id, municipality, barangay, latitude, longitude FROM "tblfarmerregistry";', engine)["latitude"]
        ),
        crs="EPSG:4326"
    ).to_crs(epsg=32651)

    if not gz.empty:
        gz_gdf = gpd.GeoDataFrame(
            gz,
            geometry=gpd.points_from_xy(gz.longitude, gz.latitude),
            crs="EPSG:4326"
        ).to_crs(epsg=32651)

        all_farms_gdf["nearest_ground_zero_m"] = all_farms_gdf.geometry.apply(
            lambda geom: gz_gdf.distance(geom).min()
        )
        all_farms_gdf["nearest_ground_zero_km"] = all_farms_gdf["nearest_ground_zero_m"] / 1000
    else:
        all_farms_gdf["nearest_ground_zero_km"] = None

    # --- Merge distances into df_final ---
    df_final = pd.concat([df_period, df_missing], ignore_index=True)
    df_final = df_final.drop_duplicates(subset=["id"])
    df_final = df_final.merge(
        all_farms_gdf[["id","municipality","barangay","nearest_ground_zero_km"]],
        on=["id","municipality","barangay"],
        how="left"
    )

    # --- Compute road proximity features ---
    road_file = "hotosm_phl_roads_lines_geojson.geojson"
    quezon_file = "ShapeFiles/QuezonMunicipalities-Barangays.shp"
    roads = gpd.read_file(road_file).to_crs(epsg=32651)
    roads = roads[roads["highway"].isin(["primary","secondary","tertiary"])]
    quezon = gpd.read_file(quezon_file).to_crs(epsg=32651)
    roads = gpd.overlay(roads, quezon, how="intersection")

    def road_proximity_to_gz(farm_geom, gz_gdf, roads):
        if not gz_gdf.empty:
            gz_union = gz_gdf.unary_union
            gz_roads = roads[roads.distance(gz_union) <= 2000]
            return gz_roads.distance(farm_geom).min() / 1000 if not gz_roads.empty else None
        else:
            return None

    df_final = gpd.GeoDataFrame(
        df_final,
        geometry=gpd.points_from_xy(df_final.longitude, df_final.latitude),
        crs="EPSG:4326"
    ).to_crs(epsg=32651)

    df_final["nearest_road_to_ground_zero_km"] = df_final.geometry.apply(
        lambda geom: road_proximity_to_gz(geom, gz_gdf, roads)
    )
    df_final["access_road_near_outbreak"] = df_final["nearest_road_to_ground_zero_km"].apply(
        lambda d: 1 if d is not None and d <= 1 else 0
    )

    # --- Predict risk ---
    preds = model.predict(df_final[[
        "farm_density","total_farm_population","nearest_ground_zero_km",
        "biosecurity_level1_compliant","cluster_id","nearest_road_km",
        "access_road_nearby","nearest_road_to_ground_zero_km",
        "access_road_near_outbreak","outbreak_group","asf_positive"
    ]])
    df_final["risk_level"] = preds

    # --- Risk scoring + zoning ---
    def compute_risk_score(row):
        score = 0
        if row["outbreak_group"] == 1: score += 20
        if row["total_farm_population"] > 100: score += 15
        elif row["total_farm_population"] > 50: score += 10
        if row["nearest_ground_zero_km"] is not None:
            if row["nearest_ground_zero_km"] <= 1: score += 30
            elif row["nearest_ground_zero_km"] <= 3: score += 20
            elif row["nearest_ground_zero_km"] <= 5: score += 10
        if row["biosecurity_level1_compliant"] == 0: score += 15
        if row["nearest_road_km"] <= 0.5 or row["access_road_nearby"] == 1: score += 10
        return min(score, 100)

    def zoning_outcome(score):
        if score >= 70:
            return "Infected/Buffer Zone"
        elif score >= 40:
            return "Buffer/Surveillance Zone"
        else:
            return "Protected/Surveillance Zone"
        
    df_final["risk_score"] = df_final.apply(compute_risk_score, axis=1)

    def classify_risk(score):
        if score < 40:
            return "Low"
        elif score < 70:
            return "Moderate"
        else:
            return "High"

    df_final["risk_level"] = df_final["risk_score"].apply(classify_risk)
    df_final["zoning"] = df_final["risk_score"].apply(zoning_outcome)

    # --- Ensure all barangays included ---
    all_barangays = pd.read_sql(
    'SELECT id, municipality, barangay, latitude, longitude FROM "tblfarmerregistry";',
    engine
    )
    df_final = all_barangays.merge(
        df_final,
        on=["id", "municipality", "barangay"],
        how="left"
    )
    df_final = df_final.rename(columns={
    "latitude_x": "latitude",
    "longitude_x": "longitude"
})

# Optionally drop the other set
    df_final = df_final.drop(columns=["latitude_y", "longitude_y"], errors="ignore")

    df_final = df_final.fillna({
        "risk_level": "Low",
        "risk_score": 0,
        "zoning": "Protected/Surveillance Zone"
    })


    # --- Return summary ---
    df_final = df_final.replace({np.nan: None})
    #print(df_final.columns)
    #print(df_final[["id","municipality","barangay","latitude","longitude"]].head(10))
    result = df_final[[
        "municipality", "barangay","latitude","longitude","risk_level", "risk_score", "zoning"
    ]].to_dict(orient="records")

    print("Period:", period_value, "Records:", len(result))
    return result



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


@app.post("/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    contents = await file.read()
    xls = pd.ExcelFile(io.BytesIO(contents))

    all_records, failed_records = [], []
    upload_time = datetime.now()

    barangays = None
    if gpd is not None and os.path.exists("barangays.shp"):
        barangays = gpd.read_file("barangays.shp").to_crs(epsg=3857)
        barangays["area_km2"] = barangays.geometry.area / 1e6
    roads_gdf = None

    if gpd is not None and os.path.exists("hotosm_phl_roads_lines_geojson.geojson"):
        roads_gdf = gpd.read_file("hotosm_phl_roads_lines_geojson.geojson").to_crs(epsg=3857)
        roads_gdf = roads_gdf[roads_gdf["highway"].isin(["primary", "secondary", "tertiary"])]
        quezon = gpd.read_file("ShapeFiles/QuezonMunicipalities-Barangays.shp").to_crs(epsg=3857)
        roads_gdf = gpd.overlay(roads_gdf, quezon, how="intersection")

    with engine.connect() as conn:
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            df.columns = df.columns.str.strip()

            df = df.rename(columns={
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
                "Compliant to Biosecurity Level (0,1,2)": "biosecurity_level1_compliant"
            })

            # Fill missing lat/long by barangay defaults
            barangay_defaults = {}
            for _, row in df.iterrows():
                if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
                    barangay = str(row["barangay"]).strip()
                    if barangay not in barangay_defaults:
                        barangay_defaults[barangay] = (
                            safe_float(row["latitude"]),
                            safe_float(row["longitude"])
                        )
            for idx, row in df.iterrows():
                barangay = str(row["barangay"]).strip()
                if barangay in barangay_defaults:
                    if pd.isna(row["latitude"]) or str(row["latitude"]).strip() == "":
                        df.at[idx, "latitude"] = barangay_defaults[barangay][0]
                    if pd.isna(row["longitude"]) or str(row["longitude"]).strip() == "":
                        df.at[idx, "longitude"] = barangay_defaults[barangay][1]

            # Clustering
            coords = df[["latitude", "longitude"]].dropna().astype(float).to_numpy()
            if len(coords) > 0:
                coords_rad = np.radians(coords)
                db = DBSCAN(eps=5/6371, min_samples=2, metric='haversine').fit(coords_rad)
                df.loc[df[["latitude", "longitude"]].dropna().index, "cluster_id"] = db.labels_
            else:
                df["cluster_id"] = -1
            

            # Process each row
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                row_dict["latitude"] = safe_float(row_dict.get("latitude"))
                row_dict["longitude"] = safe_float(row_dict.get("longitude"))
                row_dict["total_farm_population"] = safe_int(row_dict.get("total_farm_population"), 0)
                row_dict["contact_number"] = clean_contact(row_dict.get("contact_number"))
            # ✅ Compute nearest road distance
                if roads_gdf is not None and row_dict["latitude"] and row_dict["longitude"]:
                    if roads_gdf.crs != "EPSG:3857":
                        roads_gdf = roads_gdf.to_crs(epsg=3857)
                    pt = gpd.GeoDataFrame(geometry=[Point(row_dict["longitude"], 
                    row_dict["latitude"])], crs="EPSG:4326").to_crs(epsg=3857)
                    nearest_road_m = roads_gdf.distance(pt.geometry.iloc[0]).min() if not roads_gdf.empty else None
                    row_dict["nearest_road_km"] = (nearest_road_m / 1000).item()
                    row_dict["access_road_nearby"] = (nearest_road_m <= 1000).item()  # 2 km threshold
                else:
                     row_dict["nearest_road_km"] = 0.0
                     row_dict["access_road_nearby"] = False
                # print("Major highways in Quezon:", len(roads_gdf))
                # print("Farmer:", row_dict.get("farmer_name"))
                # print("Lat/Lon:", row_dict["latitude"], row_dict["longitude"])
                # print("Roads CRS:", roads_gdf.crs)
                # print("Nearest road meters:", nearest_road_m)
                # print("Nearest road km:", row_dict["nearest_road_km"])
                # print("Access road nearby:", row_dict["access_road_nearby"])



                # Farm type mapping
                farm_type_raw = str(row_dict.get("type_of_farm")).strip().upper() if pd.notna(row_dict.get("type_of_farm")) else ""
               # print("Raw farm type:", farm_type_raw) 
                if farm_type_raw in ["SC", "CM", "COMMERCIAL", "C", "COM"]:
                    row_dict["type_of_farm"] = "Small Commercial"
                elif farm_type_raw in ["BY", "BACKYARD", "B", "BYD"]:
                    row_dict["type_of_farm"] = "Backyard"
                else:
                    row_dict["type_of_farm"] = "Unknown"

                # Boolean fields
                val = str(row_dict.get("rsba_registered")).strip().upper() if pd.notna(row_dict.get("rsba_registered")) else ""
                row_dict["rsba_registered"] = val in ["Y", "YES", "1", "TRUE"]
                val2 = str(row_dict.get("biosecurity_level1_compliant")).strip().upper() if pd.notna(row_dict.get("biosecurity_level1_compliant")) else ""
                row_dict["biosecurity_level1_compliant"] = val2 in ["Y", "YES", "1", "TRUE"]

                try:
                    with conn.begin():
                        # Nearest farm distance
                        if row_dict["latitude"] and row_dict["longitude"]:
                            farm_coords = (row_dict["latitude"], row_dict["longitude"])
                            all_coords = [(safe_float(r["latitude"]), safe_float(r["longitude"]))
                                          for _, r in df.iterrows() if pd.notna(r["latitude"]) and pd.notna(r["longitude"])]
                            nearest_farm_km = min([haversine(farm_coords, c) for c in all_coords if c != farm_coords], default=None)
                        else:
                            nearest_farm_km = None

                        # Farm count per barangay
                        farm_count = len(df[df["barangay"] == row_dict.get("barangay")])

                        # Cluster ID
                        cluster_id = int(row_dict.get("cluster_id")) if pd.notna(row_dict.get("cluster_id")) else -1

                        # Farm density
                        bname = str(row_dict.get("barangay")).strip()
                        density_val = None
                        if barangays is not None and "barangay" in barangays.columns and bname in barangays["barangay"].values:
                            area_km2 = float(barangays.loc[barangays["barangay"] == bname, "area_km2"].values[0])
                            if area_km2 > 0:
                                density_val = farm_count / area_km2
                        else:
                            density_val = farm_count

                        # Insert directly into tblFarmerRegistry
                        # 🔍 Check if farmer already 
                        try:
                            existing = conn.execute(text("""
                                SELECT id, farmer_name FROM tblfarmerregistry
                                WHERE farmer_name = :farmer_name
                                  AND municipality = :municipality
                                  AND barangay = :barangay
                            """), {
                                "farmer_name": row_dict.get("farmer_name"),
                                "municipality": row_dict.get("municipality"),
                                "barangay": row_dict.get("barangay")
                            }).fetchone()
                        except Exception as e:
                            print({"error": f"Database query error: {e}"})
                        existing = conn.execute(text("""
                            SELECT id, farmer_name FROM tblfarmerregistry
                            WHERE farmer_name = :farmer_name
                              AND municipality = :municipality
                              AND barangay = :barangay
                        """), {
                            "farmer_name": row_dict.get("farmer_name"),
                            "municipality": row_dict.get("municipality"),
                            "barangay": row_dict.get("barangay")
                        }).fetchone()

                        if existing:
                            farmer_id = existing[0]
                            farmer_name = existing[1]
                        else:
                            result = conn.execute(text("""
                                INSERT INTO tblFarmerRegistry (
                                    date_uploaded, farmer_name, municipality, barangay, latitude, longitude,
                                    contact_number, type_of_farm, total_farm_population,
                                    rsba_registered, rsba_control_number, biosecurity_level1_compliant,
                                    farm_density, nearest_farm_km, cluster_id,nearest_road_km, access_road_nearby
                                ) VALUES (
                                    :upload_time, :farmer_name, :municipality, :barangay, :latitude, :longitude,
                                    :contact_number, :type_of_farm, :total_farm_population,
                                    :rsba_registered, :rsba_control_number, :biosecurity_level1_compliant,
                                    :farm_density, :nearest_farm_km, :cluster_id,:nearest_road_km, :access_road_nearby
                                )
                                RETURNING id
                            """), {
                                "upload_time": upload_time,
                                "farmer_name": row_dict.get("farmer_name"),
                                "municipality": row_dict.get("municipality"),
                                "barangay": row_dict.get("barangay"),
                                "latitude": row_dict.get("latitude"),
                                "longitude": row_dict.get("longitude"),
                                "contact_number": row_dict.get("contact_number"),
                                "type_of_farm": row_dict.get("type_of_farm"),
                                "total_farm_population": row_dict.get("total_farm_population"),
                                "rsba_registered": row_dict.get("rsba_registered"),
                                "rsba_control_number": row_dict.get("rsba_control_number"),
                                "biosecurity_level1_compliant": row_dict.get("biosecurity_level1_compliant"),
                                "farm_density": density_val,
                                "nearest_farm_km": nearest_farm_km,
                                "cluster_id": cluster_id,
                                "nearest_road_km": row_dict.get("nearest_road_km"),        
                                "access_road_nearby": row_dict.get("access_road_nearby") 
                            })

                            row_returned = result.fetchone()
                            farmer_id = row_returned[0]

                            # Insert into tblSwinePopulation (swinepopulation = total_farm_population)
                            conn.execute(text("""
                                INSERT INTO tblswinepopulation (
                                    farmer_id, swine_population, dateadded
                                ) VALUES (
                                    :farmer_id, :swinepopulation, :dateadded
                                )
                            """), {
                                "farmer_id": farmer_id,
                                "swinepopulation": row_dict.get("total_farm_population"),
                                "dateadded": datetime.now()
                            })
                        #   print("Inserted farmer:", row_dict.get("farmer_name"))
                            all_records.append(clean_dict(row_dict))

                except Exception as e:
                    print("Insert failed for row:", row_dict, "Error:", e)
                    failed_records.append({
                        "row": clean_dict(row_dict),
                        "reason": f"DB insert error: {e}"
                    })

    return {"farmers": all_records, "failed": failed_records}
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
