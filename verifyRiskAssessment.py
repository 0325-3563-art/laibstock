"""
Independent verification of the ASF risk assessment (trainModel.py output).

It rebuilds the assessment from the RAW database tables WITHOUT importing trainModel.py,
using a different distance method (WGS84 geodesic instead of UTM), then compares it with
farm_risk_latest.csv (or any CSV with the same columns).

Predictors re-checked
  1. nearness to the ASF-positive case (ground zero)     -> DA/BAI zone + risk level
  2. total swine population                              \
  3. farm density                                         |  within-zone score
  4. clustering (cluster size, cases in cluster)          |  (rule-based mode)
  5. biosecurity compliance                               |
  6. access-road link between farm and nearest case      /
  7. municipal outbreak (>= 2 positive farms)            -> score boost

Usage (database, same env var as trainModel.py):
    python verify_risk_assessment.py --csv farm_risk_latest.csv --gz 13.8471997 121.395465
Usage (exported tables):
    python verify_risk_assessment.py --csv out.csv --farms farms.csv --cases cases.csv --gz 13.8471997 121.395465
Options: --as-of 2026-10-10   assessment date (default: today)
         --env PATH_TO_.env   or   --db-url "postgresql+psycopg2://user:pw@host:5432/db"

Outputs: verification_report.csv, verification_mismatches.csv, data_quality_issues.csv
"""
import argparse
import os
import warnings

import numpy as np
import pandas as pd
from pyproj import Geod, Transformer
from scipy.stats import spearmanr
from sklearn.cluster import DBSCAN

warnings.filterwarnings("ignore")
GEOD = Geod(ellps="WGS84")

# ---- rules restated independently (DA/BAI table + weights agreed in the project) ----
EDGES_KM = (1.0, 7.0, 10.0)
ZONES = [  # name, level, band_lo, band_hi, zone_lo_km, zone_hi_km
    ("Infected Zone", "High", 75, 100, 0.0, 1.0),
    ("Buffer Zone", "Moderate", 50, 75, 1.0, 7.0),
    ("Surveillance Zone", "Low", 25, 50, 7.0, 10.0),
    ("Protected/Free Zone", "Low", 0, 25, 10.0, 50.0),
]
CAP_KM = 50.0
W = dict(prox=35, bio=20, pop=15, dens=10, clus=10, road=10)
OUTBREAK_MIN, OUTBREAK_BOOST = 2, 15
ROAD_NEAR_KM = 0.5
SCORE_TOL, DIST_TOL = 0.3, 0.05
# same defaults / environment variables as trainModel.py
CLUSTER_EPS_M = float(os.environ.get("ASF_CLUSTER_EPS_M", 1000))
CLUSTER_MIN = int(os.environ.get("ASF_CLUSTER_MIN", 3))
COORD_MAX_KM = float(os.environ.get("ASF_COORD_MAX_KM", 30))
UNV_LEVEL, UNV_ZONE = "Unverified", "Unverified (check coordinates)"


# ------------------------------------------------------------------ data
def load_raw(args):
    if args.farms and args.cases:
        farms, cases = pd.read_csv(args.farms), pd.read_csv(args.cases)
    else:
        from dotenv import find_dotenv, load_dotenv
        from sqlalchemy import create_engine
        if args.env:
            load_dotenv(args.env, override=True)
        else:                                   # look in the current folder, then the script's folder
            load_dotenv(find_dotenv(usecwd=True)) or load_dotenv(find_dotenv())
        url = args.db_url or os.environ.get("ASF_DATABASE_URL")
        if not url:
            raise SystemExit(
                "\nASF_DATABASE_URL not found. Do ONE of these:\n"
                "  1) python verifyRiskAssessment.py --env C:\\path\\to\\.env\n"
                "  2) python verifyRiskAssessment.py --db-url \"postgresql+psycopg2://user:password@host:5432/dbname\"\n"
                "  3) PowerShell:  $env:ASF_DATABASE_URL=\"postgresql+psycopg2://user:password@host:5432/dbname\"\n"
                "  4) copy this script into the same folder as trainModel.py and its .env\n")
        eng = create_engine(url)
        farms = pd.read_sql('''SELECT id, latitude, longitude, municipality, barangay,
                total_farm_population, biosecurity_level1_compliant, farm_density,
                nearest_road_km, access_road_nearby FROM "tblfarmerregistry"''', eng)
        cases = pd.read_sql('''SELECT farm_id, MIN(COALESCE(lab_result_date, date_reported)) AS onset
                FROM "tbldiseasereports" WHERE LOWER(status)='positive'
                AND COALESCE(lab_result_date, date_reported) IS NOT NULL GROUP BY farm_id''', eng)
    cases["onset"] = pd.to_datetime(cases["onset"])
    return farms, cases


def geod_km(lat1, lon1, lat2, lon2):
    a, b, c, d = np.broadcast_arrays(*[np.asarray(v, float) for v in (lat1, lon1, lat2, lon2)])
    return GEOD.inv(b, a, d, c)[2] / 1000.0


# ------------------------------------------------------------------ independent rebuild
def rebuild(farms, cases, as_of):
    f = farms.copy()
    f["lat"] = pd.to_numeric(f["latitude"], errors="coerce")
    f["lon"] = pd.to_numeric(f["longitude"], errors="coerce")
    f["biosec_ok"] = f["biosecurity_level1_compliant"].fillna(0).astype(int)
    f["access"] = f["access_road_nearby"].fillna(0).astype(int)
    f["road_km"] = f["nearest_road_km"].astype(float)
    f["road_km"] = f["road_km"].fillna(f["road_km"].median())
    f["pop"] = f["total_farm_population"].fillna(0).astype(int)
    f["dens"] = f["farm_density"].astype(float).fillna(0)
    f["road_ok"] = ((f["road_km"] <= ROAD_NEAR_KM) | (f["access"] == 1)).astype(int)
    # coordinate validity: (1) inside the Philippines, (2) not a far outlier from the median farm
    inbox = (f["lat"].between(4, 22) & f["lon"].between(115, 128)).to_numpy()
    x = np.full(len(f), np.nan); y = np.full(len(f), np.nan)
    if inbox.any():
        x[inbox], y[inbox] = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True).transform(
            f.loc[inbox, "lon"].values, f.loc[inbox, "lat"].values)
    mx, my = np.nanmedian(x), np.nanmedian(y)
    far = inbox & (np.hypot(x - mx, y - my) / 1000.0 > COORD_MAX_KM)
    f["coord_issue"] = np.where(~inbox, "missing/impossible coordinates", "")
    f.loc[far, "coord_issue"] = f"outlier: > {COORD_MAX_KM:.0f} km from the median farm"
    vmask = inbox & ~far
    valid = pd.Series(vmask, index=f.index)
    f["valid"] = valid

    # clustering from coordinates (DBSCAN) - uses no case data
    f["cluster"], f["cluster_size"] = -1, 1
    if vmask.sum() >= 2:
        lab = DBSCAN(eps=CLUSTER_EPS_M, min_samples=CLUSTER_MIN).fit_predict(np.c_[x[vmask], y[vmask]])
        sizes = pd.Series(lab).value_counts()
        f.loc[valid, "cluster"] = lab
        f.loc[valid, "cluster_size"] = [int(sizes[l]) if l != -1 else 1 for l in lab]

    known = cases[cases["onset"] <= as_of].merge(
        f[["id", "lat", "lon", "valid", "municipality", "cluster", "road_ok"]],
        left_on="farm_id", right_on="id", how="left")
    f["is_pos"] = f["id"].isin(known["farm_id"])
    pos_xy = known[known["valid"] == True]  # noqa: E712

    # distance to nearest confirmed positive (geodesic) + road link to that case
    d = np.full(len(f), CAP_KM)
    link = np.zeros(len(f), int)
    if len(pos_xy):
        mat = np.vstack([geod_km(f["lat"].values, f["lon"].values, a, b)
                         for a, b in zip(pos_xy["lat"], pos_xy["lon"])])
        mat = np.where(np.isnan(mat), CAP_KM * 10, mat)
        j, dm = mat.argmin(axis=0), mat.min(axis=0)
        ok = f["valid"].to_numpy()
        d[ok] = np.minimum(dm[ok], CAP_KM)
        case_road = pos_xy["road_ok"].to_numpy()[j]
        link[ok] = ((case_road[ok] == 1) & (f["road_ok"].to_numpy()[ok] == 1) & (dm[ok] <= 10)).astype(int)
    f["exp_km"], f["road_link"] = d, link

    # zone / level from the DA/BAI distance rule
    zi = np.select([d <= EDGES_KM[0], d <= EDGES_KM[1], d <= EDGES_KM[2]], [0, 1, 2], default=3)
    if known.empty:                       # no confirmed case at all -> everyone Protected/Low
        zi[:] = 3
    f["exp_zone"] = [ZONES[i][0] for i in zi]
    f["exp_level"] = [ZONES[i][1] for i in zi]

    # municipal outbreak
    muni_n = known.groupby("municipality")["farm_id"].nunique()
    f["muni_pos"] = f["municipality"].map(muni_n).fillna(0).astype(int)
    f["exp_outbreak"] = (f["muni_pos"] >= OUTBREAK_MIN).astype(int)
    cc = known[known["cluster"] != -1].groupby("cluster").size()
    f["cluster_cases"] = np.where(f["cluster"] == -1, 0, f["cluster"].map(cc).fillna(0))

    # rule-based within-zone index and score (only meaningful for non-positive farms)
    lo = np.array([ZONES[i][4] for i in zi]); hi = np.array([ZONES[i][5] for i in zi])
    prox = np.clip(1 - (d - lo) / np.maximum(hi - lo, 1e-9), 0, 1)
    risk = ~f["is_pos"]
    dens = f.loc[risk, "dens"].rank(pct=True).reindex(f.index).fillna(0)
    clus = np.where(f["cluster_cases"] > 0, 0.7, 0.0) + 0.3 * np.clip(f["cluster_size"] / 10, 0, 1)
    idx = (W["prox"] * prox + W["bio"] * (f["biosec_ok"] == 0) + W["pop"] * np.clip(f["pop"] / 200, 0, 1)
           + W["dens"] * dens + W["clus"] * clus + W["road"] * (0.4 * f["road_ok"] + 0.6 * f["road_link"]))
    idx = np.clip(idx + OUTBREAK_BOOST * (f["muni_pos"] >= OUTBREAK_MIN), 0, 100)
    f["exp_score_rule"] = [ZONES[i][2] + (ZONES[i][3] - ZONES[i][2]) * v / 100 for i, v in zip(zi, idx)]
    f["band_lo"] = [ZONES[i][2] for i in zi]; f["band_hi"] = [ZONES[i][3] for i in zi]

    # confirmed positives are ground zero
    f.loc[f["is_pos"], ["exp_zone", "exp_level", "exp_km", "exp_score_rule"]] = ["Infected Zone", "High", 0.0, 100.0]
    f.loc[f["is_pos"], ["band_lo", "band_hi"]] = [75, 100]
    # farms with untrustworthy coordinates are not zoned
    unv = (~f["valid"]) & (~f["is_pos"])
    f.loc[unv, ["exp_zone", "exp_level"]] = [UNV_ZONE, UNV_LEVEL]
    f.loc[unv, ["exp_km", "exp_score_rule", "band_lo", "band_hi"]] = np.nan
    f["unv"] = unv
    return f, known


def table_mode(out, known, as_of, exp):
    """CSV/table has no farm id (e.g. copied from the web page): check each ROW by its coordinates."""
    print("\nNo 'id' column -> TABLE MODE: checking each row's level/zone from its own coordinates only.")
    lat = pd.to_numeric(out["latitude"], errors="coerce").to_numpy()
    lon = pd.to_numeric(out["longitude"], errors="coerce").to_numpy()
    ok = ~np.isnan(lat) & ~np.isnan(lon) & (lat > 4) & (lat < 22) & (lon > 115) & (lon < 128)
    ref = exp[exp["valid"]]
    if ok.any() and len(ref):
        far = np.zeros(len(out), bool)
        far[ok] = geod_km(lat[ok], lon[ok], ref["lat"].median(), ref["lon"].median()) > COORD_MAX_KM
        ok &= ~far
    pos = known[known["valid"] == True]  # noqa: E712
    d = np.full(len(out), CAP_KM)
    if len(pos):
        mat = np.vstack([geod_km(lat, lon, a, b) for a, b in zip(pos["lat"], pos["lon"])])
        d[ok] = np.minimum(np.nan_to_num(mat.min(axis=0), nan=CAP_KM)[ok], CAP_KM)
    zi = np.select([d <= 1, d <= 7, d <= 10], [0, 1, 2], default=3)
    if known.empty:
        zi[:] = 3
    t = out.copy()
    t["exp_km"] = d.round(2)
    t["exp_zone"] = [ZONES[i][0] for i in zi]; t["exp_level"] = [ZONES[i][1] for i in zi]
    t["band_lo"] = [ZONES[i][2] for i in zi]; t["band_hi"] = [ZONES[i][3] for i in zi]
    t["coords_ok"] = ok
    unv = ~ok
    t.loc[unv, "exp_zone"] = UNV_ZONE; t.loc[unv, "exp_level"] = UNV_LEVEL
    t.loc[unv, ["band_lo", "band_hi", "exp_km"]] = np.nan
    t["level_ok"] = t["risk_level"] == t["exp_level"]
    t["zone_ok"] = (t["zoning"] == t["exp_zone"]) if "zoning" in t else True
    t["band_ok"] = t["risk_score"].between(t["band_lo"] - 0.1, t["band_hi"] + 0.1) | \
        (unv & t["risk_score"].isna())
    print(f"As of {as_of.date()} | rows: {len(t)} | confirmed positive farms in DB: {len(known)}")
    for c in ("level_ok", "zone_ok", "band_ok"):
        print(f"{c:10s} {t[c].mean() * 100:6.2f}%   ({(~t[c]).sum()} failures)")
    print("\n=== LEVEL COUNTS: table vs independent ===")
    print(pd.concat([t["risk_level"].value_counts().rename("table"),
                     t["exp_level"].value_counts().rename("expected")], axis=1).fillna(0).astype(int))
    bad = t[~(t["level_ok"] & t["zone_ok"] & t["band_ok"])]
    bad.to_csv("verification_mismatches.csv", index=False)
    t.sort_values("exp_km").to_csv("verification_report.csv", index=False)
    print(f"\nRows failing any check: {len(bad)} / {len(t)} -> verification_mismatches.csv")
    print(f"Rows with missing/impossible coordinates: {(~ok).sum()}")
    print(f"Rows within 100 m of a zone boundary (verify by hand): "
          f"{sum(any(abs(k - e) < 0.1 for e in EDGES_KM) for k in d)}")
    pct = 100 * (1 - len(bad) / max(len(t), 1))
    print(f"\n=== OVERALL AGREEMENT: {pct:.2f}% of rows pass all checks ===")
    if bad.empty:
        print("\nRESULT: every row's level and zone match the DA/BAI distance rules.")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="farm_risk_latest.csv")
    ap.add_argument("--farms"); ap.add_argument("--cases")
    ap.add_argument("--gz", nargs=2, type=float, metavar=("LAT", "LON"))
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--env", help="path to the .env file that holds ASF_DATABASE_URL")
    ap.add_argument("--db-url", help="database URL (overrides the environment variable)")
    a = ap.parse_args()
    as_of = pd.Timestamp(a.as_of) if a.as_of else pd.Timestamp.today().normalize()

    farms, cases = load_raw(a)
    exp, known = rebuild(farms, cases, as_of)
    out = pd.read_csv(a.csv)
    out.columns = [c.strip().lower().replace(" ", "_") for c in out.columns]
    for need in ("risk_level", "risk_score", "latitude", "longitude"):
        if need not in out.columns:
            raise SystemExit(f"CSV is missing the column '{need}'. Columns found: {list(out.columns)}")
    if "id" not in out.columns:
        return table_mode(out, known, as_of, exp)
    for opt in ("nearest_case_km", "zoning", "method", "municipality_outbreak"):
        if opt not in out.columns:
            print(f"NOTE: CSV has no '{opt}' column - that check is skipped. "
                  "(Re-run the NEW trainModel.py to produce a complete farm_risk_latest.csv.)")
    m = exp.merge(out, on="id", how="outer", suffixes=("", "_csv"), indicator=True)
    print(f"As of {as_of.date()} | farms in DB: {len(farms)} | in CSV: {len(out)} | "
          f"confirmed positive farms: {int(exp['is_pos'].sum())}")
    miss = m[m["_merge"] != "both"]
    if len(miss):
        print(f"!! {len(miss)} farm ids appear in only one of DB/CSV (stale CSV?)")
    m = m[m["_merge"] == "both"].copy()
    method = out["method"].iloc[0] if "method" in out else "rule-based"
    print(f"CSV method: {method}")

    # ---- ground zero
    if a.gz:
        near = exp[exp["is_pos"] & (geod_km(exp["lat"], exp["lon"], a.gz[0], a.gz[1]) < 0.05)]
        print("\nGround zero:", f"matches positive farm id(s) {near['id'].tolist()}" if len(near) else
              "!! NO confirmed positive farm sits at those coordinates (check farm_id / lat-lon of the case)")

    # ---- core comparison
    m["level_ok"] = m["risk_level"] == m["exp_level"]
    m["zone_ok"] = (m["zoning"] == m["exp_zone"]) if "zoning" in m else True
    m["dist_ok"] = (((m["nearest_case_km"] - m["exp_km"]).abs() <= DIST_TOL) | m["is_pos"] | m["unv"]) \
        if "nearest_case_km" in m else True
    m["band_ok"] = m["risk_score"].between(m["band_lo"] - 0.1, m["band_hi"] + 0.1) | \
        (m["unv"] & m["risk_score"].isna())
    m["outbreak_ok"] = m["municipality_outbreak"] == m["exp_outbreak"] if "municipality_outbreak" in m else True
    if method == "rule-based":
        m["score_ok"] = ((m["risk_score"] - m["exp_score_rule"]).abs() <= SCORE_TOL) | \
            (m["unv"] & m["risk_score"].isna())
    else:
        m["score_ok"] = m["band_ok"]
    checks = ["level_ok", "zone_ok", "dist_ok", "band_ok", "outbreak_ok", "score_ok"]
    print("\n=== PASS RATE PER CHECK ===")
    for c in checks:
        print(f"{c:12s} {m[c].mean() * 100:6.2f}%   ({(~m[c]).sum()} failures)")
    print("\n=== COUNTS: CSV vs independent ===")
    print(pd.concat([m["risk_level"].value_counts().rename("csv_level"),
                    m["exp_level"].value_counts().rename("expected_level")], axis=1).fillna(0).astype(int))
    if "zoning" in m:
        print(pd.concat([m["zoning"].value_counts().rename("csv_zone"),
                         m["exp_zone"].value_counts().rename("expected_zone")], axis=1).fillna(0).astype(int))

    bad = m[~m[checks].all(axis=1)]
    cols = ["id", "municipality", "barangay", "lat", "lon", "exp_km", "nearest_case_km", "risk_level",
            "exp_level", "zoning", "exp_zone", "risk_score", "exp_score_rule"] + checks
    cols = [c for c in cols if c in m.columns]
    bad[cols].to_csv("verification_mismatches.csv", index=False)
    m[cols].sort_values("exp_km").to_csv("verification_report.csv", index=False)
    edge = m[[any(abs(k - e) < 0.1 for e in EDGES_KM) for k in m["exp_km"]]]
    print(f"\nFarms failing any check: {len(bad)} / {len(m)}  -> verification_mismatches.csv")
    print(f"Farms within 100 m of a zone boundary (verify by hand): {len(edge)}")

    # ---- predictor direction check (does the score move the right way inside each zone?)
    if method == "rule-based":
        print("\n=== PREDICTOR DIRECTION CHECK (Spearman of risk_score inside each zone; expect + signs) ===")
        t = m[~m["is_pos"] & ~m["unv"]].copy()
        t["closer_to_case"] = -t["exp_km"]; t["biosec_noncompliant"] = (t["biosec_ok"] == 0).astype(int)
        preds = ["closer_to_case", "biosec_noncompliant", "pop", "dens", "cluster_cases", "road_ok", "road_link"]
        rows = []
        for z, g in t.groupby("exp_zone"):
            rows.append({"zone": z, "n": len(g), **{p: (round(spearmanr(g["risk_score"], g[p])[0], 2)
                         if g[p].nunique() > 1 else np.nan) for p in preds}})
        print(pd.DataFrame(rows).to_string(index=False))

    # ---- data quality
    print("\n=== DATA QUALITY ===")
    bad_c = exp[exp["coord_issue"] != ""]
    issues = [dict(id=r.id, municipality=r.municipality, barangay=r.barangay, lat=r.lat, lon=r.lon,
                   issue=r.coord_issue) for r in bad_c.itertuples()]
    pd.DataFrame(issues).to_csv("data_quality_issues.csv", index=False)
    print(f"Farms with missing/impossible coordinates: {int(bad_c['coord_issue'].str.startswith('missing').sum())}")
    print(f"Farms > {COORD_MAX_KM:.0f} km from the median farm (likely typos): "
          f"{int(bad_c['coord_issue'].str.startswith('outlier').sum())}  -> expected label: {UNV_LEVEL}")
    notin = set(cases["farm_id"]) - set(farms["id"])
    print(f"Positive cases whose farm_id is not in the registry: {len(notin)} {sorted(notin)[:10]}")
    nocoord = known[known["valid"] != True]
    print(f"Positive cases whose farm has no usable coordinates (cannot create a zone): {len(nocoord)}")
    dup = farms.groupby([farms["latitude"].round(6), farms["longitude"].round(6)]).size()
    print(f"Coordinate pairs shared by 5+ farms (centroids / copied locations): {(dup >= 5).sum()}")
    print("Saved data_quality_issues.csv")
    pct = 100 * (1 - len(bad) / max(len(m), 1))
    print(f"\n=== OVERALL AGREEMENT: {pct:.2f}% of farms ({len(m) - len(bad)} / {len(m)}) pass ALL checks ===")
    print("(agreement with the DA/BAI rules + scoring recomputation - NOT predictive accuracy)")
    if bad.empty:
        print("\nRESULT: assessment matches the independent recomputation for every farm.")


if __name__ == "__main__":
    main()