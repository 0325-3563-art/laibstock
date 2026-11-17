from fastapi import FastAPI, UploadFile, File, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io, math, os
from sqlalchemy import create_engine, text
from datetime import datetime,date
import numpy as np
from sklearn.cluster import DBSCAN
from pydantic import BaseModel
import joblib

try:
    import geopandas as gpd
except ImportError:
    gpd = None

app = FastAPI()

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

@app.post("/ml-risk/{period_type}/{period_value}")
def ml_risk(period_type: str, period_value: str, data: FarmData):
    X_new = pd.DataFrame([{
        "farm_density": data.farm_density,
        "total_farm_population": data.total_farm_population,
        "nearest_ground_zero_km": data.nearest_ground_zero_km,
        "biosecurity_level1_compliant": int(data.biosecurity_level1_compliant),
        "cluster_id": data.cluster_id
    }])

    # Select correct model dictionary
    if period_type == "month":
        model = monthly_models.get(period_value)
    elif period_type == "quarter":
        model = quarterly_models.get(period_value)
    elif period_type == "semi_annual":
        model = semiannual_models.get(period_value)
    elif period_type == "year":
        model = annual_models.get(period_value)
    else:
        return {"error": "Invalid period type"}

    if not model:
        return {"error": f"No model found for {period_value}"}

    predicted_risk = model.predict(X_new)[0]
    return {"risk_level": predicted_risk}
@app.post("/ml-risk/year")
def ml_risk_year(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD"),
    data: FarmData = None
):
    # Convert to datetime
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    X_new = pd.DataFrame([{
        "farm_density": data.farm_density,
        "total_farm_population": data.total_farm_population,
        "nearest_ground_zero_km": data.nearest_ground_zero_km,
        "biosecurity_level1_compliant": int(data.biosecurity_level1_compliant),
        "cluster_id": data.cluster_id
    }])

    # Pick annual model (you can decide logic: by year or custom)
    model = None
    for year_key, annual_model in annual_models.items():
        if str(start_dt.year) == year_key:
            model = annual_model
            break

    if not model:
        return {"error": f"No annual model found for {start_dt.year}"}

    predicted_risk = model.predict(X_new)[0]
    return {"risk_level": predicted_risk}


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
                        conn.execute(text("""
                            INSERT INTO tblFarmerRegistry (
                                date_uploaded, farmer_name, municipality, barangay, latitude, longitude,
                                contact_number, type_of_farm, total_farm_population,
                                rsba_registered, rsba_control_number, biosecurity_level1_compliant,
                                farm_density, nearest_farm_km, cluster_id
                            ) VALUES (
                                :upload_time, :farmer_name, :municipality, :barangay, :latitude, :longitude,
                                :contact_number, :type_of_farm, :total_farm_population,
                                :rsba_registered, :rsba_control_number, :biosecurity_level1_compliant,
                                :farm_density, :nearest_farm_km, :cluster_id
                            )
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
                            "cluster_id": cluster_id
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
