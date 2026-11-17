"""
ASF risk scoring - DA/BAI zoning aligned, hybrid, leakage-free.

ZONE (and therefore risk level) is set by straight-line distance to the nearest
confirmed ASF-positive farm known as of the assessment date:

    0-1 km    Infected Zone (Red)               -> High
    1-7 km    Buffer Zone (Yellow)              -> Moderate
    7-10 km   Surveillance Zone (Light Green)   -> Low
    > 10 km   Protected/Free Zone (Dark Green)  -> Low  (same level, different zoning)

RISK SCORE (0-100) ranks farms *inside* their zone.
A municipality with >= 2 confirmed positive farms is flagged as an OUTBREAK (extra score boost).
Farms with missing/impossible/outlier coordinates are labeled "Unverified" (not zoned) until fixed. Each zone owns a score band
(Infected 75-100, Buffer 50-75, Surveillance 25-50, Protected 0-25) and the farm's
position in the band depends on: closeness to the case, swine population, farm
density, clustering, biosecurity compliance, and access-road link to the case.

  * Not enough confirmed cases -> rule-based within-zone index (expert weights).
  * Enough confirmed cases     -> RandomForest probability, ranked within each zone.
The zone itself is ALWAYS rule-based (it is policy, not a prediction).

Config via environment variables:
  ASF_DATABASE_URL   postgresql+psycopg2://user:password@host:5432/dbname   (required)
  ASF_MIN_POSITIVE   min. positive farms before supervised training (default 30)
  ASF_MIN_SNAPSHOTS  min. distinct months with cases (default 6)

Leakage controls (supervised mode)
  * label = "farm turns positive within HORIZON_DAYS after snapshot date T"
  * features use only cases known at T; a farm is never its own nearest case
  * already-positive farms are excluded from that snapshot
  * time-based train/test split with a gap; no ground-truth columns in X
"""
import os
import warnings

import joblib
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, classification_report, roc_auc_score
from sqlalchemy import create_engine
from dotenv import load_dotenv
load_dotenv()

warnings.filterwarnings("ignore")

# ---------------- Config ----------------
MODEL_PATH = "./asf_risk_model.pkl"
OUTPUT_CSV = "./farm_risk_latest.csv"

HORIZON_DAYS = 30
MIN_POSITIVE_FARMS = int(os.environ.get("ASF_MIN_POSITIVE", 30))
MIN_SNAPSHOTS = int(os.environ.get("ASF_MIN_SNAPSHOTS", 6))
CAP_KM = 50.0
TEST_FRACTION = 0.2
# Clustering (DBSCAN on projected coordinates). 5 km / min 2 chained almost every farm in a dense
# municipality into ONE giant cluster, so clustering carried no information. Tighter defaults:
CLUSTER_EPS_M = float(os.environ.get("ASF_CLUSTER_EPS_M", 1000))      # neighbour radius (m)
CLUSTER_MIN_SAMPLES = int(os.environ.get("ASF_CLUSTER_MIN", 3))       # farms needed to form a cluster

# Coordinate validation: farms with missing / impossible / far-outlier coordinates cannot be zoned.
COORD_MAX_KM = float(os.environ.get("ASF_COORD_MAX_KM", 30))          # max km from the median farm
UNVERIFIED_LEVEL = "Unverified"
UNVERIFIED_ZONE = "Unverified (check coordinates)"

# ---- DA/BAI zones: (name, color, level, max_km, score_band_low, score_band_high, action) ----
ZONES = [
    ("Infected Zone",            "Red",         "High",     1.0,    75, 100,
     "Strict quarantine, culling, total movement ban"),
    ("Buffer Zone",              "Yellow",      "Moderate", 7.0,    50, 75,
     "Controlled transport, heightened surveillance, biosecurity reinforcement"),
    ("Surveillance Zone",        "Light Green", "Low",      10.0,   25, 50,
     "Preventive surveillance, limited movement with veterinary clearance"),
    ("Protected/Free Zone",      "Dark Green",  "Low",      np.inf, 0,  25,
     "Normal movement allowed, continued monitoring"),
]
ZONE_EDGES_KM = [0.0, 1.0, 7.0, 10.0]       # lower edge of each zone (km)
ROAD_NEAR_KM = 0.5                          # "near an access road"

# Within-zone index weights (sum = 100)
W_PROXIMITY, W_BIOSEC, W_POP, W_DENSITY, W_CLUSTER, W_ROAD = 35, 20, 15, 10, 10, 10

# Municipal outbreak: >= 2 confirmed positive farms (any barangays) in the same municipality.
# It is a flag + score boost only; zone radii stay exactly as the DA/BAI table defines them.
OUTBREAK_MIN_FARMS = 2
OUTBREAK_BOOST = 15         # index points added inside the farm's own zone band (capped at 100)

# If no confirmed case is known as of the assessment date, every farm is Protected/Free.
# Scores are still returned (vulnerability only) so farms can be ranked.
CAP_LEVEL_WITHOUT_CASES = True

# Static = built from the registry only (never from case data), so they cannot leak the label.
STATIC_FEATURES = [
    "farm_density", "total_farm_population", "biosecurity_level1_compliant",
    "nearest_road_km", "access_road_nearby", "road_access",
    "cluster_size", "nearest_farm_km",
]
# Dynamic = built from ASF positives, recomputed "as of" each date, never for the farm itself.
DYNAMIC_FEATURES = ["nearest_case_km", "cases_within_5km", "cases_within_10km",
                    "municipality_cases", "cluster_cases", "road_link_to_case"]
FEATURES = STATIC_FEATURES + DYNAMIC_FEATURES


# ---------------- Data ----------------
def add_spatial_features(farms):
    """Recompute cluster + nearest-neighbour from coordinates, consistently for ALL farms.
    (The cluster_id stored in the registry was produced by separate DBSCAN runs per upload /
    per new farm, so the same number can mean different groups.)  Uses no case data."""
    farms["cluster"] = -1
    farms["cluster_size"] = 1
    farms["nearest_farm_km"] = CAP_KM
    valid = farms[["x", "y"]].notna().all(axis=1)
    if valid.sum() >= 2:
        xy = farms.loc[valid, ["x", "y"]].to_numpy()
        labels = DBSCAN(eps=CLUSTER_EPS_M, min_samples=CLUSTER_MIN_SAMPLES).fit_predict(xy)
        sizes = pd.Series(labels).value_counts()
        n_cl = len(set(labels)) - (1 if -1 in labels else 0)
        biggest = int(sizes.drop(-1, errors="ignore").max()) if n_cl else 0
        print(f"Clustering (DBSCAN eps={CLUSTER_EPS_M:.0f} m, min_samples={CLUSTER_MIN_SAMPLES}): "
              f"{n_cl} clusters, largest = {biggest} farms ({biggest / len(labels):.0%} of valid farms), "
              f"{int((labels == -1).sum())} farms in no cluster")
        if n_cl and biggest / len(labels) > 0.5:
            print("WARNING: one cluster holds >50% of farms - clustering is not informative. "
                  "Lower ASF_CLUSTER_EPS_M or raise ASF_CLUSTER_MIN.")
        farms.loc[valid, "cluster"] = labels
        farms.loc[valid, "cluster_size"] = [int(sizes[l]) if l != -1 else 1 for l in labels]
        d, _ = cKDTree(xy).query(xy, k=2)
        farms.loc[valid, "nearest_farm_km"] = np.minimum(d[:, 1] / 1000.0, CAP_KM)
    return farms


def load_data(engine):
    farms = pd.read_sql(
        """
        SELECT id, latitude, longitude, municipality, barangay,
               total_farm_population, biosecurity_level1_compliant,
               farm_density, nearest_road_km, access_road_nearby
        FROM "tblfarmerregistry"
        """, engine)
    cases = pd.read_sql(
        """
        SELECT farm_id, MIN(COALESCE(lab_result_date, date_reported)) AS onset
        FROM "tbldiseasereports"
        WHERE LOWER(status) = 'positive'
          AND COALESCE(lab_result_date, date_reported) IS NOT NULL
        GROUP BY farm_id
        """, engine)
    cases["onset"] = pd.to_datetime(cases["onset"])

    farms["biosecurity_level1_compliant"] = farms["biosecurity_level1_compliant"].fillna(0).astype(int)
    farms["access_road_nearby"] = farms["access_road_nearby"].fillna(0).astype(int)
    farms["nearest_road_km"] = farms["nearest_road_km"].astype(float)
    farms["nearest_road_km"] = farms["nearest_road_km"].fillna(farms["nearest_road_km"].median())
    farms["farm_density"] = farms["farm_density"].astype(float).fillna(0)
    farms["total_farm_population"] = farms["total_farm_population"].fillna(0).astype(int)

    farms["road_access"] = ((farms["nearest_road_km"] <= ROAD_NEAR_KM) |
                            (farms["access_road_nearby"] == 1)).astype(int)

    tf = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
    lat = pd.to_numeric(farms["latitude"], errors="coerce")
    lon = pd.to_numeric(farms["longitude"], errors="coerce")
    farms["x"], farms["y"] = tf.transform(lon.to_numpy(float), lat.to_numpy(float))
    farms[["x", "y"]] = farms[["x", "y"]].replace([np.inf, -np.inf], np.nan)   # missing lat/lon
    # (1) outside the Philippines (e.g. longitude typed as 13.9) -> impossible
    impossible = ~(lat.between(4, 22) & lon.between(115, 128))
    farms.loc[impossible, ["x", "y"]] = np.nan
    # (2) far from the bulk of the registry (e.g. 121.895 typed instead of 121.3x) -> outlier
    ok = farms[["x", "y"]].notna().all(axis=1)
    mx, my = farms.loc[ok, "x"].median(), farms.loc[ok, "y"].median()
    outlier = ok & (np.hypot(farms["x"] - mx, farms["y"] - my) / 1000.0 > COORD_MAX_KM)
    farms.loc[outlier, ["x", "y"]] = np.nan
    farms["coord_valid"] = farms[["x", "y"]].notna().all(axis=1).astype(int)
    print(f"Coordinate check: {int(impossible.sum())} missing/impossible, {int(outlier.sum())} farther than "
          f"{COORD_MAX_KM:.0f} km from the median farm -> {int((farms['coord_valid'] == 0).sum())} "
          f"farms marked '{UNVERIFIED_LEVEL}' (fix their latitude/longitude).")
    farms = add_spatial_features(farms)

    cases = cases.merge(farms[["id", "x", "y", "municipality", "cluster", "road_access"]],
                        left_on="farm_id", right_on="id", how="left").drop(columns="id")
    nocoord = cases[cases["x"].isna() | cases["y"].isna()]
    if len(nocoord):
        print(f"WARNING: {len(nocoord)} positive case(s) have unusable farm coordinates "
              f"(farm_id {nocoord['farm_id'].tolist()[:10]}) - they cannot create zones until fixed.")
    return farms, cases


# ---------------- As-of features ----------------
def dynamic_features(farms, cases, as_of):
    """Case-based features using only cases with onset <= as_of.
    `farms` must exclude farms already positive at as_of.
    Farms/cases without coordinates are tolerated (they just get no distance info)."""
    known_all = cases[cases["onset"] <= as_of]
    out = pd.DataFrame(index=farms.index)
    out["nearest_case_km"] = CAP_KM
    out["cases_within_5km"] = 0
    out["cases_within_10km"] = 0
    out["road_link_to_case"] = 0
    out["municipality_cases"] = farms["municipality"].map(
        known_all.groupby("municipality").size()).fillna(0).to_numpy()
    in_cluster = known_all[known_all["cluster"] != -1]          # -1 = not in any cluster
    out["cluster_cases"] = np.where(
        farms["cluster"] == -1, 0,
        farms["cluster"].map(in_cluster.groupby("cluster").size()).fillna(0)).astype(int)

    known = known_all.dropna(subset=["x", "y"])
    valid = farms[["x", "y"]].notna().all(axis=1)
    if known.empty or not valid.any():
        return out

    tree = cKDTree(known[["x", "y"]].to_numpy())
    pts = farms.loc[valid, ["x", "y"]].to_numpy()
    d, idx = tree.query(pts)
    out.loc[valid, "nearest_case_km"] = np.minimum(d / 1000.0, CAP_KM)
    # road pathway proxy: farm AND its nearest case both sit on/near an access road, within 10 km
    case_road = known["road_access"].to_numpy()[idx]
    farm_road = farms.loc[valid, "road_access"].to_numpy()
    out.loc[valid, "road_link_to_case"] = ((case_road == 1) & (farm_road == 1) & (d <= 10000)).astype(int)
    out.loc[valid, "cases_within_5km"] = tree.query_ball_point(pts, r=5000, return_length=True)
    out.loc[valid, "cases_within_10km"] = tree.query_ball_point(pts, r=10000, return_length=True)
    return out


# ---------------- Zoning + rule-based index ----------------
def assign_zone(nearest_case_km):
    """Return zone name, color, level, action, zone lower/upper km, band low/high for each farm."""
    d = np.asarray(nearest_case_km, dtype=float)
    idx = np.select([d <= 1.0, d <= 7.0, d <= 10.0], [0, 1, 2], default=3)
    col = lambda i: np.array([z[i] for z in ZONES], dtype=object)[idx]
    lo_km = np.array(ZONE_EDGES_KM + [10.0])[idx]
    hi_km = np.array([z[3] for z in ZONES])[idx]
    return pd.DataFrame({"zoning": col(0), "zone_color": col(1), "risk_level": col(2),
                         "recommended_action": col(6), "zone_lo_km": lo_km, "zone_hi_km": hi_km,
                         "band_lo": col(4).astype(float), "band_hi": col(5).astype(float)})


def rule_index(feat, zone):
    """0-100 ranking index within a zone from the factors you listed."""
    d = feat["nearest_case_km"].to_numpy()
    hi = np.where(np.isinf(zone["zone_hi_km"]), CAP_KM, zone["zone_hi_km"])
    span = np.maximum(hi - zone["zone_lo_km"], 1e-9)
    proximity = np.clip(1 - (d - zone["zone_lo_km"]) / span, 0, 1)   # 1 at inner edge of zone, 0 at outer

    biosec = (feat["biosecurity_level1_compliant"] == 0).astype(float)
    pop = np.clip(feat["total_farm_population"] / 200.0, 0, 1)
    density = feat["farm_density"].rank(pct=True) if len(feat) > 1 else 0.0
    cluster = np.where(feat["cluster_cases"] > 0, 0.7, 0.0) + 0.3 * np.clip(feat["cluster_size"] / 10.0, 0, 1)
    road = 0.4 * feat["road_access"] + 0.6 * feat["road_link_to_case"]

    idx = (W_PROXIMITY * proximity + W_BIOSEC * biosec + W_POP * pop +
           W_DENSITY * density + W_CLUSTER * cluster + W_ROAD * road)
    return pd.Series(np.asarray(idx, dtype=float), index=feat.index).clip(0, 100)


# ---------------- Supervised training ----------------
def build_snapshots(farms, cases):
    snap_dates = pd.date_range(cases["onset"].min().to_period("M").to_timestamp(),
                               cases["onset"].max().to_period("M").to_timestamp(), freq="MS")
    onset_by_farm = cases.set_index("farm_id")["onset"]
    data_end = cases["onset"].max()
    # keep only snapshots whose full HORIZON_DAYS label window is observable
    snap_dates = [T for T in snap_dates if T + pd.Timedelta(days=HORIZON_DAYS) <= data_end]
    frames = []
    for T in snap_dates:
        pos_before = set(cases.loc[cases["onset"] <= T, "farm_id"])
        at_risk = farms[~farms["id"].isin(pos_before) & (farms["coord_valid"] == 1)]
        snap = pd.concat([at_risk[["id"] + STATIC_FEATURES], dynamic_features(at_risk, cases, T)], axis=1)
        onset = at_risk["id"].map(onset_by_farm)
        snap["label"] = ((onset > T) & (onset <= T + pd.Timedelta(days=HORIZON_DAYS))).astype(int)
        snap["snapshot"] = T
        frames.append(snap)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def new_rf():
    return RandomForestClassifier(n_estimators=300, min_samples_leaf=5,
                                  class_weight="balanced_subsample", random_state=42, n_jobs=-1)


def train_supervised(farms, cases):
    """Returns a fitted model, or None if the time split leaves too few positives."""
    data = build_snapshots(farms, cases)
    if data.empty:
        print("No snapshot has a complete label window yet - need more history.")
        return None
    snaps = sorted(data["snapshot"].unique())
    print(f"Supervised: {cases['farm_id'].nunique()} positive farms, {len(snaps)} snapshots, "
          f"{int(data['label'].sum())} positive labels / {len(data)} rows")

    test_start = pd.Timestamp(snaps[max(1, int(len(snaps) * (1 - TEST_FRACTION)))])
    train = data[data["snapshot"] + pd.Timedelta(days=HORIZON_DAYS) <= test_start]
    test = data[data["snapshot"] >= test_start]
    if train["label"].sum() < 5 or test["label"].sum() < 1:
        print("Too few positives in train/test after the time split.")
        return None

    m = new_rf().fit(train[FEATURES], train["label"])
    p = m.predict_proba(test[FEATURES])[:, 1]
    print("\n--- Time-held-out evaluation ---")
    print(f"Test base rate: {test['label'].mean():.4f}")
    print(f"PR-AUC: {average_precision_score(test['label'], p):.4f} (must beat base rate)")
    print(f"ROC-AUC: {roc_auc_score(test['label'], p):.4f}")
    print(classification_report(test["label"], (p >= 0.5).astype(int), zero_division=0))
    print(pd.Series(m.feature_importances_, index=FEATURES).sort_values(ascending=False))

    return new_rf().fit(data[FEATURES], data["label"])   # refit on all data for deployment


# ---------------- Unified prediction (used by the app) ----------------
_ARTIFACT_CACHE = {"path": None, "mtime": None, "artifact": None}


def load_artifact(model_path=MODEL_PATH):
    """Load the saved artifact once; reload automatically after retraining."""
    if not os.path.exists(model_path):
        return {"mode": "rule"}
    mtime = os.path.getmtime(model_path)
    c = _ARTIFACT_CACHE
    if c["path"] != model_path or c["mtime"] != mtime:
        c.update(path=model_path, mtime=mtime, artifact=joblib.load(model_path))
    return c["artifact"]


def predict_risk(farms, cases, as_of=None, model_path=MODEL_PATH):
    """Same output columns in both modes. Zone/level = DA/BAI distance rule; score ranks within zone."""
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today().normalize()
    artifact = load_artifact(model_path)

    is_pos = farms["id"].isin(cases.loc[cases["onset"] <= as_of, "farm_id"])
    at_risk = farms[~is_pos]
    feat = pd.concat([at_risk[STATIC_FEATURES], dynamic_features(at_risk, cases, as_of)], axis=1)

    zone = assign_zone(feat["nearest_case_km"])
    zone.index = at_risk.index
    if CAP_LEVEL_WITHOUT_CASES and not (cases["onset"] <= as_of).any():
        zone = assign_zone(np.full(len(at_risk), CAP_KM)); zone.index = at_risk.index

    if artifact["mode"] == "supervised":
        proba = artifact["model"].predict_proba(feat[artifact.get("features", FEATURES)])[:, 1]
        rf_proba = pd.Series(proba, index=at_risk.index)
        index = rf_proba.groupby(zone["zoning"]).rank(pct=True) * 100.0
        method = "supervised"
    else:
        index = rule_index(feat, zone)
        rf_proba = pd.Series(np.nan, index=at_risk.index)
        method = "rule-based"
    in_outbreak = (feat["municipality_cases"] >= OUTBREAK_MIN_FARMS)
    index = (index + OUTBREAK_BOOST * in_outbreak).clip(upper=100.0)
    score = zone["band_lo"] + (zone["band_hi"] - zone["band_lo"]) * index / 100.0

    out = farms[["id", "municipality", "barangay", "latitude", "longitude"]].copy()
    # predictors behind each assessment (used by the map popups / reports)
    for c in ["total_farm_population", "biosecurity_level1_compliant", "farm_density",
              "nearest_road_km", "access_road_nearby", "cluster_size"]:
        out[c] = farms[c]
    out["cluster_cases"] = feat["cluster_cases"].reindex(out.index)
    out["road_link_to_case"] = feat["road_link_to_case"].reindex(out.index)
    out["nearest_case_km"] = feat["nearest_case_km"].reindex(out.index).round(2)
    out["rf_probability"] = rf_proba.reindex(out.index).round(4)   # P(positive within HORIZON_DAYS)
    out["risk_score"] = score.reindex(out.index).round(1)
    for c in ["risk_level", "zoning", "zone_color", "recommended_action"]:
        out[c] = zone[c].reindex(out.index)

    # confirmed positive farms = ground zero
    out.loc[is_pos, ["risk_score", "nearest_case_km"]] = [100.0, 0.0]
    out.loc[is_pos, "risk_level"] = "High"
    out.loc[is_pos, "zoning"] = "Infected Zone"
    out.loc[is_pos, "zone_color"] = "Red"
    out.loc[is_pos, "recommended_action"] = ZONES[0][6]
    out["confirmed_positive"] = is_pos.astype(int)

    # farms whose coordinates cannot be trusted are NOT zoned (they would look 'far' = Protected)
    out["coord_valid"] = farms["coord_valid"].astype(int)
    unver = (~is_pos) & (farms["coord_valid"] == 0)
    out.loc[unver, "risk_level"] = UNVERIFIED_LEVEL
    out.loc[unver, "zoning"] = UNVERIFIED_ZONE
    out.loc[unver, "zone_color"] = "Gray"
    out.loc[unver, "recommended_action"] = "Verify the farm's latitude/longitude, then re-run the assessment"
    out.loc[unver, ["risk_score", "nearest_case_km", "rf_probability"]] = np.nan

    # municipal outbreak status as of the assessment date (applies to every farm in that municipality)
    known = cases[cases["onset"] <= as_of]
    muni_n = known.groupby("municipality")["farm_id"].nunique()
    outbreak_munis = set(muni_n[muni_n >= OUTBREAK_MIN_FARMS].index)
    out["municipality_positive_farms"] = out["municipality"].map(muni_n).fillna(0).astype(int)
    out["municipality_outbreak"] = out["municipality"].isin(outbreak_munis).astype(int)
    out["method"] = method
    return out


# ---------------- Main ----------------
if __name__ == "__main__":
    engine = create_engine(os.environ["ASF_DATABASE_URL"])
    farms, cases = load_data(engine)

    n_pos = cases["farm_id"].nunique()
    n_months = cases["onset"].dt.to_period("M").nunique()
    print(f"Ground truth available: {n_pos} positive farms across {n_months} month(s).")

    artifact = {"mode": "rule"}
    if n_pos < MIN_POSITIVE_FARMS or n_months < MIN_SNAPSHOTS:
        print(f"Random Forest NOT trained: need >= {MIN_POSITIVE_FARMS} positive farms and "
              f">= {MIN_SNAPSHOTS} months (have {n_pos} / {n_months}). "
              "Lower ASF_MIN_POSITIVE / ASF_MIN_SNAPSHOTS for a demo only.")
    if n_pos >= MIN_POSITIVE_FARMS and n_months >= MIN_SNAPSHOTS:
        model = train_supervised(farms, cases)
        if model is None:
            print("Random Forest NOT trained: see message above.")
        if model is not None:
            artifact = {"mode": "supervised", "model": model, "features": FEATURES,
                        "horizon_days": HORIZON_DAYS}
    if artifact["mode"] == "rule":
        print("Using RULE-BASED scoring (insufficient ground truth for a reliable model).")
        if n_pos:
            print("Note: known cases still raise nearby farms' scores via the exposure rules.")

    joblib.dump(artifact, MODEL_PATH)
    result = predict_risk(farms, cases)
    result.to_csv(OUTPUT_CSV, index=False)
    print(f"\nMode: {artifact['mode']}  |  saved {MODEL_PATH} and {OUTPUT_CSV}")
    print(result.groupby(["zoning", "zone_color"]).size())
    print("Municipalities in outbreak:",
          sorted(result.loc[result["municipality_outbreak"] == 1, "municipality"].dropna().unique()))