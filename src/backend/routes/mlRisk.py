from fastapi import APIRouter
from sqlalchemy import create_engine
import pandas as pd
import joblib

router = APIRouter()

DATABASE_URL = "postgresql+psycopg2://postgres:Asawanid5@localhost:5432/dbLAIBStock"
engine = create_engine(DATABASE_URL)

# Load trained model (categorical: Low/Medium/High)
model = joblib.load("risk_model.pkl")

@router.get("/ml-risk")
async def ml_risk():
    # Load tables
    farmers_df = pd.read_sql('SELECT * FROM "tbldiseaseAnalysis"', engine)
    asf_df = pd.read_sql('SELECT * FROM "tbldiseasereport"', engine)

    # Normalize column names
    farmers_df.columns = farmers_df.columns.str.lower()
    asf_df.columns = asf_df.columns.str.lower()

    # Merge datasets
    merged = pd.merge(
        farmers_df,
        asf_df[["farmer_name", "municipality", "barangay", "confirmed_asf_case"]],
        left_on=["farmername", "municipality", "barangay"],
        right_on=["farmer_name", "municipality", "barangay"],
        how="left"
    )

    merged["confirmed_asf_case"] = merged["confirmed_asf_case"].fillna("No")

    # Features for ML model
    feature_cols = [
        "farm_count",
        "nearest_farm_km",
        "rsbaregistered",
        "biosecuritylevel1compliant",
        "typeoffarm"
    ]
    X = merged[feature_cols].copy()
    X = pd.get_dummies(X, drop_first=True)

    # Align features with training schema
    X = X.reindex(columns=model.feature_names_in_, fill_value=0)

    if X.empty:
        return {"error": "No features available after merge. Check column names and data."}

    # Predict categorical risk (Low/Medium/High)
    merged["risk_level"] = model.predict(X)

    return {
    "summary": merged[[
        "farmername", "municipality", "barangay",
        "latitude", "longitude",
        "risk_level", "confirmed_asf_case"
    ]].to_dict(orient="records"),
    "total_records": len(merged)
}

    
