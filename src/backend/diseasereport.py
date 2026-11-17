from fastapi import APIRouter, UploadFile, File
import pandas as pd, io
from sqlalchemy import create_engine, text

router = APIRouter()

DATABASE_URL = "postgresql+psycopg2://postgres:Asawanid5@localhost:5432/dbLAIBStock"
engine = create_engine(DATABASE_URL)

@router.post("/upload-disease-report")
async def upload_disease_report(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_csv(io.BytesIO(contents), encoding="latin1")

    # Convert Yes/No to Boolean
    df["RSBARegistered"] = df["RSBARegistered"].map({"Yes": True, "No": False})
    df["BiosecurityLevel1Compliant"] = df["BiosecurityLevel1Compliant"].map({"Yes": True, "No": False})
    df["ConfirmedASFCaseBool"] = df["ConfirmedASFCase"].map({"Yes": True, "No": False})

    # Normalize date format
    df["Date"] = pd.to_datetime(df["Date"]).dt.date

    # Insert rows manually into your existing table
    inserted_rows = 0
    with engine.begin() as conn:  # ensures commit
        for _, row in df.iterrows():
            conn.execute(
                text("""
                    INSERT INTO tbldiseasereport
                    (report_date, farmer_name, municipality, barangay, latitude, longitude,
                     type_of_farm, total_farm_population, rsba_registered,
                     biosecurity_level1_compliant, confirmed_asf_case)
                    VALUES (:date, :farmer, :municipality, :barangay, :lat, :lon,
                            :farm_type, :population, :rsba, :biosec, :asf)
                """),
                {
                    "date": row["Date"],
                    "farmer": row["FarmerName"],
                    "municipality": row["Municipality"],
                    "barangay": row["Barangay"],
                    "lat": row["Latitude"],
                    "lon": row["Longitude"],
                    "farm_type": row["TypeOfFarm"],
                    "population": row["TotalFarmPopulation"],
                    "rsba": row["RSBARegistered"],
                    "biosec": row["BiosecurityLevel1Compliant"],
                    "asf": row["ConfirmedASFCaseBool"],
                }
            )
            inserted_rows += 1

    # Summarize confirmed ASF cases per municipality
    summary = (
        df.groupby("Municipality")["ConfirmedASFCase"]
        .apply(lambda x: (x == "Yes").sum())
        .reset_index(name="ConfirmedCases")
    )

    return {
        "message": f"{inserted_rows} rows saved to database",
        "total_records": len(df),
        "summary": summary.to_dict(orient="records"),
    }
