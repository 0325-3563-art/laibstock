import pandas as pd
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestClassifier
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
import geopandas as gpd
import os
import shapely
import warnings
from imblearn.over_sampling import SMOTE
from collections import Counter

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# print("GeoPandas:", gpd.__version__)
# print("Shapely:", shapely.__version__)

# Connect to PostgreSQL
DATABASE_URL = "postgresql+psycopg2://postgres:Asawanid5@localhost:5432/dbLAIBStock"
engine = create_engine(DATABASE_URL)

# --- Ground Zero Farms (ASF Positive) ---
ground_zero_query = """
SELECT f.id, f.latitude, f.longitude, f.total_farm_population, f.municipality
FROM "tblfarmerregistry" f
INNER JOIN "tbldiseasereports" d
ON f.id = d.farm_id
WHERE d.status = 'Positive';
"""
ground_zero = pd.read_sql(ground_zero_query, engine)

gz_gdf = gpd.GeoDataFrame(
    ground_zero,
    geometry=gpd.points_from_xy(ground_zero.longitude, ground_zero.latitude),
    crs="EPSG:4326"
).to_crs(epsg=32651)   # UTM zone

# --- All Farms with Risk Features ---
all_farms_query = """
SELECT f.id, f.latitude, f.longitude, f.municipality, f.barangay,
       f.total_farm_population, f.biosecurity_level1_compliant,
       f.farm_density, f.cluster_id,
       f.nearest_road_km, f.access_road_nearby,
       d.lab_result_date,
       CASE WHEN d.status = 'Positive' THEN 1 ELSE 0 END AS asf_positive
FROM "tblfarmerregistry" f
LEFT JOIN "tbldiseasereports" d
ON f.id = d.farm_id;
"""
all_farms = pd.read_sql(all_farms_query, engine)
all_farms["lab_result_date"] = pd.to_datetime(all_farms["lab_result_date"])

# Period columns
all_farms["month"] = all_farms["lab_result_date"].dt.to_period("M")
all_farms["quarter"] = all_farms["lab_result_date"].dt.to_period("Q")
all_farms["semi_annual"] = all_farms["lab_result_date"].dt.month.map(lambda m: 1 if m <= 6 else 2)
all_farms["year"] = all_farms["lab_result_date"].dt.year

# --- Outbreak Grouping ---
# Flag municipalities with >=2 positive cases
outbreaks = all_farms.groupby("municipality")["asf_positive"].sum()
outbreak_muns = outbreaks[outbreaks >= 2].index
all_farms["outbreak_group"] = all_farms["municipality"].apply(lambda m: 1 if m in outbreak_muns else 0)

# --- Compute distance to nearest ground zero ---
farms_gdf = gpd.GeoDataFrame(
    all_farms,
    geometry=gpd.points_from_xy(all_farms.longitude, all_farms.latitude),
    crs="EPSG:4326"
).to_crs(epsg=32651)

farms_gdf["nearest_ground_zero_m"] = farms_gdf.geometry.apply(
    lambda geom: gz_gdf.distance(geom).min() if not gz_gdf.empty else None
)
farms_gdf["nearest_ground_zero_km"] = farms_gdf["nearest_ground_zero_m"] / 1000
# --- Roads layer (Quezon only) ---
road_file = "hotosm_phl_roads_lines_geojson.geojson"
if os.path.exists(road_file):
 roads = gpd.read_file("hotosm_phl_roads_lines_geojson.geojson").to_crs(epsg=32651)
 roads = roads[roads["highway"].isin(["primary", "secondary", "tertiary"])]
 # Clip roads to Quezon Province boundary
 quezon_file = "ShapeFiles/QuezonMunicipalities-Barangays.shp"
 if os.path.exists(quezon_file):
        quezon = gpd.read_file(quezon_file).to_crs(epsg=32651)
        roads = gpd.overlay(roads, quezon, how="intersection")
 else:
        raise FileNotFoundError(f"Quezon shapefile not found: {os.path.abspath(quezon_file)}")
else:
    raise FileNotFoundError(f"Road file not found: {os.path.abspath(road_file)}")
# --- Distance of ground zero farms to nearest road ---
gz_gdf["nearest_road_m"] = gz_gdf.geometry.apply(lambda geom: roads.distance(geom).min())
gz_gdf["nearest_road_km"] = gz_gdf["nearest_road_m"] / 1000

# --- For each farm: distance to roads connected to ground zero ---
def road_proximity_to_gz(farm_geom):
    # Select roads within 2 km of any ground zero farm
    if not gz_gdf.empty:
        # Debug prints
        # print("gz_gdf type:", type(gz_gdf))
        # print("gz_gdf geometry type:", gz_gdf.geom_type.unique() if not gz_gdf.empty else "EMPTY")
        # print("gz_gdf union_all:", gz_gdf.union_all)

        
        gz_union = gz_gdf.unary_union
        gz_roads = roads[roads.distance(gz_union) <= 2000]
        return gz_roads.distance(farm_geom).min() / 1000 if not gz_roads.empty else None
    else:
        return None

farms_gdf["nearest_road_to_ground_zero_km"] = farms_gdf.geometry.apply(road_proximity_to_gz)

# --- Flag farms near outbreak roads ---
farms_gdf["access_road_near_outbreak"] = farms_gdf["nearest_road_to_ground_zero_km"].apply(
    lambda d: 1 if d is not None and d <= 1 else 0
)

# --- Sanitize types ---
farms_gdf["biosecurity_level1_compliant"] = farms_gdf["biosecurity_level1_compliant"].astype(int)
farms_gdf["access_road_nearby"] = farms_gdf["access_road_nearby"].astype(int)
farms_gdf["nearest_road_km"] = farms_gdf["nearest_road_km"].astype(float)
farms_gdf["farm_density"] = farms_gdf["farm_density"].astype(float)
farms_gdf["total_farm_population"] = farms_gdf["total_farm_population"].astype(int)

# --- Risk Scoring + Label Assignment ---
def compute_risk_score(row):
    score = 0
    if row["outbreak_group"] == 1: score += 15
    if row["total_farm_population"] > 100: score += 10
    elif row["total_farm_population"] > 50: score += 5
    if row["nearest_ground_zero_km"] <= 1: score += 25
    elif row["nearest_ground_zero_km"] <= 3: score += 15
    elif row["nearest_ground_zero_km"] <= 5: score += 10
    if row["biosecurity_level1_compliant"] == 0: score += 15
    if row["nearest_road_km"] <= 0.5 or row["access_road_nearby"] == 1: score += 5
    if "access_road_near_outbreak" in row and row["access_road_near_outbreak"] == 1:
        score += 15 
    return min(score, 100)

def classify_risk(score):
    if score < 40: return "Low"
    elif score < 70: return "Moderate"
    else: return "High"

def zoning_outcome(score):
    if score >= 70: return "Infected/Buffer Zone"
    elif score >= 40: return "Buffer/Surveillance Zone"
    else: return "Protected/Surveillance Zone"

# Apply scoring
farms_gdf["risk_score"] = farms_gdf.apply(compute_risk_score, axis=1)
farms_gdf["risk_level"] = farms_gdf["risk_score"].apply(classify_risk)
farms_gdf["zoning"] = farms_gdf["risk_score"].apply(zoning_outcome)
#print(farms_gdf[["municipality","barangay","risk_score","risk_level","zoning"]].head(20))


# --- Train models per period ---
def train_models_by_period(farms_gdf, period_col):
    models = {}
    for period, df in farms_gdf.groupby(period_col):
        X = df[[
            "farm_density",
            "total_farm_population",
            "nearest_ground_zero_km",
            "biosecurity_level1_compliant",
            "cluster_id",
            "nearest_road_km",
            "access_road_nearby",
            "nearest_road_to_ground_zero_km",   # NEW FEATURE
            "access_road_near_outbreak",        # NEW FEATURE
            "outbreak_group",
            "asf_positive"
        ]]
        y = df["risk_level"]

        # Build key for saving models
        if period_col == "month":
            key = period.strftime("%Y-%m")
        elif period_col == "quarter":
            key = period.strftime("%YQ%q")
        elif period_col == "semi_annual":
            year_val = df["year"].iloc[0]
            semi_val = int(period)
            key = f"{year_val}-S{semi_val}"
        elif period_col == "year":
            key = str(period)
        else:
            key = str(period)

        # --- Case 1: Normal training ---
        if len(y.unique()) > 1 and len(y) > 10 and all(y.value_counts() >= 2):
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, stratify=y, random_state=42
            )

            # Apply SMOTE if High class exists
            if "High" in y_train.values:
                smote = SMOTE(random_state=42, k_neighbors=2)
                X_train, y_train = smote.fit_resample(X_train, y_train)
               # print("Resampled class distribution:", Counter(y_train))

            model = RandomForestClassifier(
                n_estimators=200, random_state=42, class_weight="balanced"
            )
            model.fit(X_train, y_train)
            models[key] = model
            print(f"✅ Trained model for {key}")
            print(classification_report(y_test, model.predict(X_test), zero_division=0))

        # --- Case 2: Fallback rules (no ASF positive) ---
        elif df["asf_positive"].sum() == 0:
            def fallback_risk(row):
                if row["total_farm_population"] > 100:
                    return "Medium"
                elif row["farm_density"] > 5:
                    return "Low"
                else:
                    return "Safe"
            df["risk_level"] = df.apply(fallback_risk, axis=1)
            y = df["risk_level"]

            model = RandomForestClassifier(n_estimators=50, random_state=42)
            model.fit(X, y)
            models[key] = model
            print(f"⚠️ Fallback model trained for {key} (no ASF positive)")

        # --- Case 3: Dummy baseline ---
        else:
            model = DummyClassifier(strategy="most_frequent")
            model.fit(X, y)
            models[key] = model
            print(f"ℹ️ Baseline model saved for {key} (single class or insufficient data)")
    
    return models
    #     if len(y.unique()) > 1 and len(y) > 5:
    #         X_train, X_test, y_train, y_test = train_test_split(
    #             X, y, test_size=0.2, stratify=y, random_state=42
    #         )
    #         model = RandomForestClassifier(
    #             n_estimators=200, random_state=42, class_weight="balanced"
    #         )
    #         model.fit(X_train, y_train)
    #         if period_col == "month":
    #             key = period.strftime("%Y-%m")   # e.g. "2026-09"
    #         elif period_col == "quarter":
    #             key = period.strftime("%Y-Q%q")  # e.g. "2026-Q3"
    #         elif period_col == "semi_annual":
    #             key = f"{df['year'].iloc[0]}-S{period}"  # e.g. "2026-S2"
    #         elif period_col == "year":
    #             key = str(period)
    #         else:
    #             key = str(period)

    #         models[key] = model
    #         print(f"Trained model for {key}")
    #         print(classification_report(y_test, model.predict(X_test)))
    # return models

    #         models[str(period)] = model
    #         print(f"Trained model for {period}")
    #         print(classification_report(y_test, model.predict(X_test)))
    # return models

# Train and save models
monthly_models = train_models_by_period(farms_gdf, "month")
quarterly_models = train_models_by_period(farms_gdf, "quarter")
semiannual_models = train_models_by_period(farms_gdf, "semi_annual")
annual_models = train_models_by_period(farms_gdf, "year")

joblib.dump(monthly_models, "./risk_models_monthly.pkl")
joblib.dump(quarterly_models, "./risk_models_quarterly.pkl")
joblib.dump(semiannual_models, "./risk_models_semiannual.pkl")
joblib.dump(annual_models, "./risk_models_annual.pkl")

print("Monthly model keys:", monthly_models.keys())
print("✅ ASF risk models trained and saved.")
