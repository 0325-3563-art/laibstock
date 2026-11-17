"""
Build an interactive ASF risk map from trainModel.py's output.

    python build_risk_map.py                         # uses farm_risk_latest.csv + the database
    python build_risk_map.py --env C:\\path\\to\\.env
    python build_risk_map.py --no-db                 # CSV only (no extra farmer details)
    python build_risk_map.py --farms registry.csv    # farmer details from an exported registry

Creates
  asf_risk_map.html  - open in any browser (Leaflet; street + satellite basemaps)
  asf_risk_map.kml   - open in Google Earth (desktop, web or mobile)

Every farm is pinned (colored by risk level) with its farmer details, latitude and longitude.
Farms with missing/impossible coordinates cannot be placed on a map: they are listed in the side
panel ("Not on the map") so none is silently dropped.
Zone rings (DA/BAI) are drawn around each confirmed positive farm: 0-1 km, 1-7 km, 7-10 km.

PRIVACY: the files contain farmer details. Share them only with authorised staff.
"""
import argparse
import json
import os
from datetime import datetime
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
COLORS = {"High": "#d62728", "Moderate": "#ff9f1c", "Low": "#2ca02c", "Unverified": "#7f7f7f"}
KML_COL = {"High": "ff2827d6", "Moderate": "ff1c9fff", "Low": "ff2ca02c", "Unverified": "ff7f7f7f"}
RINGS = [(10, "Surveillance Zone (7-10 km)", "#90ee90", "4090ee90"),
         (7, "Buffer Zone (1-7 km)", "#ffd400", "4000d4ff"),
         (1, "Infected Zone (0-1 km)", "#e60000", "550000ff")]
KNOWN = {"id", "municipality", "barangay", "latitude", "longitude"}
SKIP_EXTRA = {"geom", "geometry", "password", "created_at", "updated_at", "cluster_id", "cluster"}


# ------------------------------------------------------------------ data
def get_engine(a):
    if a.no_db or (a.farms and a.cases):
        return None
    try:
        from dotenv import find_dotenv, load_dotenv
        from sqlalchemy import create_engine
        if a.env:
            load_dotenv(a.env, override=True)
        else:
            load_dotenv(find_dotenv(usecwd=True)) or load_dotenv(find_dotenv())
        url = a.db_url or os.environ.get("ASF_DATABASE_URL")
        if not url:
            print("NOTE: no database URL found -> CSV only (use --env / --db-url for farmer and case details).")
            return None
        return create_engine(url)
    except Exception as e:
        print(f"NOTE: database connection not available ({e.__class__.__name__}) -> CSV only.")
        return None


def load_registry(a, eng):
    try:
        if a.farms:
            reg = pd.read_csv(a.farms, dtype=str)          # keep phone numbers' leading zeros
            reg["id"] = pd.to_numeric(reg["id"], errors="coerce")
            return reg
        return pd.read_sql('SELECT * FROM "tblfarmerregistry"', eng) if eng is not None else None
    except Exception as e:
        print(f"NOTE: could not read the registry ({e.__class__.__name__}) -> no farmer details.")
        return None


def load_cases(a, eng):
    """First positive date and number of positive reports per farm (for the ASF-positive pins)."""
    try:
        if a.cases:
            c = pd.read_csv(a.cases).rename(columns={"onset": "first_positive"})
        elif eng is not None:
            c = pd.read_sql("""SELECT farm_id, MIN(COALESCE(lab_result_date, date_reported)) AS first_positive,
                               COUNT(*) AS positive_reports FROM "tbldiseasereports"
                               WHERE LOWER(status) = 'positive' GROUP BY farm_id""", eng)
        else:
            return None
        if "positive_reports" not in c.columns:
            c["positive_reports"] = 1
        return c.rename(columns={"farm_id": "id"})[["id", "first_positive", "positive_reports"]]
    except Exception as e:
        print(f"NOTE: could not read case dates ({e.__class__.__name__}).")
        return None


def clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    return v if isinstance(v, (int, float, bool)) else str(v)


def build_records(df, reg, cases=None, max_extra=30):
    df = df.copy()
    if cases is not None and len(cases):
        df = df.merge(cases, on="id", how="left")
    extras = []
    if reg is not None and "id" in reg.columns:
        extras = [c for c in reg.columns if c not in df.columns and c.lower() not in SKIP_EXTRA
                  and reg[c].notna().any()][:max_extra]
        df = df.merge(reg[["id"] + extras], on="id", how="left")
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    df["_ok"] = lat.between(4, 22) & lon.between(115, 128)
    recs = []
    for r in df.to_dict("records"):
        g = lambda k: clean(r.get(k))
        recs.append(dict(
            id=g("id"), lat=g("latitude") if r["_ok"] else None, lon=g("longitude") if r["_ok"] else None,
            raw_lat=g("latitude"), raw_lon=g("longitude"), ok=bool(r["_ok"]),
            level=g("risk_level") or "Unverified", score=g("risk_score"), zone=g("zoning"),
            km=g("nearest_case_km"), action=g("recommended_action"), pos=int(r.get("confirmed_positive") or 0),
            muni=g("municipality"), brgy=g("barangay"), pop=g("total_farm_population"),
            bio=g("biosecurity_level1_compliant"), dens=g("farm_density"), road_km=g("nearest_road_km"),
            access=g("access_road_nearby"), csize=g("cluster_size"), ccases=g("cluster_cases"),
            rlink=g("road_link_to_case"), outbreak=g("municipality_outbreak"),
            onset=g("first_positive"), nrep=g("positive_reports"),
            extra={c.replace("_", " ").title(): g(c) for c in extras if g(c) is not None}))
    return recs


# ------------------------------------------------------------------ HTML
TEMPLATE = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASF Risk Map</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.css">
<style>
*{box-sizing:border-box} html,body{height:100%;margin:0;font-family:Segoe UI,Arial,sans-serif;font-size:13px}
#app{display:flex;height:100%} #side{width:320px;overflow:auto;padding:12px;border-right:1px solid #ccc;background:#fafafa}
#map{flex:1} h1{font-size:17px;margin:0 0 4px} .muted{color:#666;font-size:12px}
.lv{display:flex;align-items:center;gap:6px;margin:4px 0} .dot{width:14px;height:14px;border-radius:50%;border:1px solid #fff;box-shadow:0 0 2px #000}
.box{margin:10px 0;padding:8px;background:#fff;border:1px solid #ddd;border-radius:6px}
input[type=text]{width:100%;padding:6px;border:1px solid #bbb;border-radius:4px}
.pin{width:100%;height:100%;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.6)}
.pin.pos{border-color:#000;border-width:3px}
.pin span{display:block;transform:rotate(45deg);color:#fff;font-weight:700;text-align:center;font-size:15px;line-height:24px}
.pop{max-width:300px;max-height:320px;overflow:auto} .pop h3{margin:0 0 4px;font-size:14px}
.pop table{border-collapse:collapse;width:100%} .pop th{text-align:left;color:#555;font-weight:600;padding:1px 6px 1px 0;vertical-align:top;white-space:nowrap}
.pop td{padding:1px 0} .pop h4{margin:8px 0 2px;font-size:12px;color:#333;border-bottom:1px solid #ddd}
.badge{display:inline-block;color:#fff;padding:1px 7px;border-radius:9px;font-weight:600}
details{margin-top:6px} summary{cursor:pointer;font-weight:600} .nm{padding:3px 0;border-bottom:1px solid #eee}
@media(max-width:700px){#app{flex-direction:column-reverse}#side{width:100%;height:42%}}
</style></head><body>
<div id="app"><div id="side">
<h1>ASF Risk Map</h1><div class="muted" id="meta"></div>
<div class="box" id="levels"></div>
<div class="box"><input type="text" id="q" placeholder="Search id, barangay, farmer...">
<label><input type="checkbox" id="rings" checked> DA/BAI zone rings around confirmed cases</label><br>
<label><input type="checkbox" id="grp" checked> Group nearby pins (click a group to zoom / spread)</label>
<div class="muted" id="shown" style="margin-top:4px"></div></div>
<div class="box"><b>Zones (distance from a confirmed case)</b><div id="zl"></div></div>
<details class="box" id="nm"><summary id="nms"></summary><div id="nml"></div></details>
</div><div id="map"></div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.js"></script>
<script>
const DATA = __DATA__;
const COLORS = __COLORS__, RINGS = __RINGS__, POSC = '#8e24aa';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, d=2, u='') => (v === null || v === undefined) ? '-' : (typeof v === 'number' ? v.toFixed(d) : v) + u;
const rows = o => Object.entries(o).filter(([k,v]) => v !== null && v !== undefined && v !== '')
  .map(([k,v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('');

function popup(f){
  const title = f.pos ? `Confirmed ASF-positive farm #${esc(f.id)}` : `Farm #${esc(f.id)}`;
  const bio = f.bio === null ? '-' : (f.bio == 1 ? 'Compliant' : 'NOT compliant');
  const road = f.road_km === null ? '-' : f.road_km.toFixed(2) + ' km' + (f.access == 1 ? ' (access road nearby)' : '');
  const casebox = f.pos ? '<h4>ASF case</h4><table>' + rows({'First confirmed positive': f.onset, 'Positive reports': f.nrep}) + '</table>' : '';
  const risk = {'Risk level': `<span class="badge" style="background:${COLORS[f.level]||'#777'}">${esc(f.level)}</span>`,
    'Risk score': f.score === null ? '-' : f.score.toFixed(1) + ' / 100', 'DA/BAI zone': f.zone, 'Action': f.action,
    'Distance to nearest case': f.pos ? '0 km (confirmed case)' : fmt(f.km, 2, ' km'),
    'Municipal outbreak': f.outbreak === null ? '-' : (f.outbreak == 1 ? 'Yes (2+ positive farms)' : 'No')};
  const pred = {'Swine population': fmt(f.pop, 0), 'Farm density': fmt(f.dens, 2), 'Biosecurity Level 1': bio,
    'Nearest access road': road, 'Road link to nearest case': f.rlink === null ? '-' : (f.rlink == 1 ? 'Yes' : 'No'),
    'Cluster': f.csize === null ? '-' : `${f.csize} farm(s), ${f.ccases ?? 0} case(s)`};
  const rawRow = (k,v)=>`<tr><th>${k}</th><td>${v}</td></tr>`;
  return `<div class="pop"><h3>${title}</h3>
   ${casebox}${Object.keys(f.extra).length ? '<h4>Farmer details</h4><table>'+rows(f.extra)+'</table>' : ''}
   <h4>Location</h4><table>${rawRow('Municipality',esc(f.muni||'-'))}${rawRow('Barangay',esc(f.brgy||'-'))}
   ${rawRow('Latitude',esc(f.raw_lat ?? '-'))}${rawRow('Longitude',esc(f.raw_lon ?? '-'))}</table>
   <h4>Risk assessment</h4><table>${Object.entries(risk).map(([k,v])=>rawRow(k, k==='Risk level'?v:esc(v ?? '-'))).join('')}</table>
   <h4>Predictors</h4><table>${rows(pred)}</table></div>`;
}
function icon(f){
  const s = f.pos ? 32 : 20;
  return L.divIcon({className:'', iconSize:[s,s], iconAnchor:[s/2, s*0.95], popupAnchor:[0,-s],
    html:`<div class="pin ${f.pos?'pos':''}" style="background:${f.pos?POSC:(COLORS[f.level]||'#777')}">${f.pos?'<span>!</span>':''}</div>`});
}
const map = L.map('map');
const street = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {maxZoom:19, attribution:'Tiles &copy; Esri'});
const carto = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {subdomains:'abcd', maxZoom:19, attribution:'&copy; OpenStreetMap contributors &copy; CARTO'});
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom:19, attribution:'Imagery &copy; Esri'});
const labels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {maxZoom:19});
street.addTo(map);
L.control.layers({'Street map (Esri)':street, 'Street map (CARTO)':carto, 'Satellite (Esri)':sat}, {'Place names':labels}, {collapsed:false}).addTo(map);
L.control.scale().addTo(map);

// zone rings around confirmed cases
const ringLayer = L.layerGroup().addTo(map);
RINGS.forEach(([km, name, col]) => DATA.cases.forEach(c =>
  L.circle([c.lat, c.lon], {radius: km*1000, color: col, weight: 1, fillColor: col, fillOpacity: km===1?0.22:0.10, interactive:false}).addTo(ringLayer)));

// pins
const items = DATA.farms.filter(f => f.ok).map(f => {
  const m = L.marker([f.lat, f.lon], {icon: icon(f), title: f.pos ? `#${f.id} ASF-POSITIVE` : `#${f.id} ${f.level}`, zIndexOffset: f.pos ? 1000 : 0});
  m.bindPopup(() => popup(f), {maxWidth: 320});
  f._q = [f.id, f.muni, f.brgy, f.level, f.zone, ...Object.values(f.extra)].join(' ').toLowerCase();
  return {f, m};
});
const cluster = L.markerClusterGroup({maxClusterRadius: 35, spiderfyOnMaxZoom: true, disableClusteringAtZoom: 18});
const plain = L.layerGroup();
const posLayer = L.layerGroup().addTo(map);      // ASF-positive cases: never grouped, always on top
const active = {Low:true, Moderate:true, High:true, Unverified:true};

function render(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const useGrp = document.getElementById('grp').checked;
  cluster.clearLayers(); plain.clearLayers(); map.removeLayer(cluster); map.removeLayer(plain);
  const vis = items.filter(({f}) => !f.pos && active[f.level] !== false && (!q || f._q.includes(q))).map(i => i.m);
  posLayer.clearLayers();
  const posVis = document.getElementById('showpos').checked ? items.filter(({f}) => f.pos && (!q || f._q.includes(q))) : [];
  posVis.forEach(i => posLayer.addLayer(i.m));
  const grp = useGrp ? cluster : plain;
  vis.forEach(m => grp.addLayer(m)); grp.addTo(map);
  document.getElementById('shown').textContent = `Showing ${vis.length + posVis.length} of ${DATA.farms.length} farms (${items.length} placed on the map)`;
}
// side panel
const total = lv => DATA.farms.filter(f => f.level === lv).length;
document.getElementById('meta').textContent = `As of ${DATA.meta.as_of} | method: ${DATA.meta.method} | ${DATA.cases.length} confirmed positive farm(s)`;
document.getElementById('levels').innerHTML = ['High','Moderate','Low','Unverified'].map(lv =>
  `<label class="lv"><input type="checkbox" data-lv="${lv}" checked><span class="dot" style="background:${COLORS[lv]}"></span><b>${lv}</b> (${total(lv)})${lv==='Unverified'?' <span class="muted">- fix coordinates</span>':''}</label>`).join('')
  + `<label class="lv"><input type="checkbox" id="showpos" checked><span class="dot" style="background:${POSC};border:2px solid #000"></span><b>ASF-positive cases</b> (${DATA.farms.filter(f => f.pos).length})</label>`
  + `<div class="muted">Purple pin with "!" = confirmed ASF-positive farm (always shown, never grouped)</div>`;
document.querySelectorAll('[data-lv]').forEach(cb => cb.onchange = () => {active[cb.dataset.lv] = cb.checked; render();});
document.getElementById('zl').innerHTML = RINGS.slice().reverse().map(([km,name,col]) =>
  `<div class="lv"><span class="dot" style="background:${col}"></span>${name}</div>`).join('') + '<div class="lv"><span class="dot" style="background:#006400"></span>Protected/Free Zone (&gt;10 km)</div>';
document.getElementById('q').oninput = render;
document.getElementById('showpos').onchange = render;
document.getElementById('grp').onchange = render;
document.getElementById('rings').onchange = e => e.target.checked ? ringLayer.addTo(map) : map.removeLayer(ringLayer);
const nm = DATA.farms.filter(f => !f.ok);
document.getElementById('nms').textContent = `Not on the map: ${nm.length} (no usable coordinates)`;
document.getElementById('nml').innerHTML = nm.length ? nm.map(f => `<div class="nm"><b>#${esc(f.id)}</b> ${esc(f.brgy||'')}, ${esc(f.muni||'')}<br>
  <span class="muted">lat ${esc(f.raw_lat ?? '-')}, lon ${esc(f.raw_lon ?? '-')} ${Object.values(f.extra).slice(0,2).map(esc).join(' | ')}</span></div>`).join('')
  : '<span class="muted">All farms are on the map.</span>';
const good = items.filter(({f}) => f.level !== 'Unverified').map(i => i.m.getLatLng());
const pts = good.length ? good : items.map(i => i.m.getLatLng());
if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.1)); else map.setView([13.9, 121.35], 11);
render();
</script></body></html>'''


def write_html(recs, cases, meta, path):
    payload = json.dumps(dict(farms=recs, cases=cases, meta=meta), allow_nan=False).replace("</", "<\\/")
    rings = [[km, name, col] for km, name, col, _ in RINGS]
    html = (TEMPLATE.replace("__DATA__", payload).replace("__COLORS__", json.dumps(COLORS))
            .replace("__RINGS__", json.dumps(rings)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# ------------------------------------------------------------------ KML (Google Earth)
def circle_ring(lat, lon, km, n=72):
    az = np.linspace(0, 360, n, endpoint=True)
    lons, lats, _ = GEOD.fwd(np.full(n, lon), np.full(n, lat), az, np.full(n, km * 1000.0))
    return " ".join(f"{x:.6f},{y:.6f},0" for x, y in zip(lons, lats))


def write_kml(recs, cases, meta, path):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f'<name>ASF Risk Map ({escape(meta["as_of"])})</name>']
    for lv, col in KML_COL.items():
        out.append(f'<Style id="s{lv}"><IconStyle><color>{col}</color><scale>1.0</scale><Icon><href>'
                   'http://maps.google.com/mapfiles/kml/paddle/wht-blank.png</href></Icon></IconStyle>'
                   '<LabelStyle><scale>0</scale></LabelStyle></Style>')
    out.append('<Style id="sPos"><IconStyle><color>ffaa248e</color><scale>1.5</scale><Icon><href>'
               'http://maps.google.com/mapfiles/kml/paddle/wht-stars.png</href></Icon></IconStyle></Style>')
    for km, name, _, kcol in RINGS:
        out.append(f'<Style id="z{km}"><LineStyle><color>ff{kcol[2:]}</color>'
                   f'<width>2</width></LineStyle><PolyStyle><color>{kcol}</color></PolyStyle></Style>')
    out.append('<Folder><name>DA/BAI zone rings</name><open>0</open>')
    for km, name, _, _ in RINGS:
        for c in cases:
            out.append(f'<Placemark><name>{escape(name)} - farm #{c["id"]}</name><styleUrl>#z{km}</styleUrl><Polygon>'
                       f'<outerBoundaryIs><LinearRing><coordinates>{circle_ring(c["lat"], c["lon"], km)}</coordinates>'
                       '</LinearRing></outerBoundaryIs></Polygon></Placemark>')
    out.append('</Folder>')
    for lv in ["ASF-positive cases", "High", "Moderate", "Low", "Unverified"]:
        out.append(f'<Folder><name>{lv if lv.startswith("ASF") else lv + " risk"}</name>')
        sel = (lambda r: r["pos"] and r["ok"]) if lv.startswith("ASF") else (lambda r: r["level"] == lv and r["ok"] and not r["pos"])
        for f in (r for r in recs if sel(r)):
            det = {**({"First confirmed positive": f["onset"], "Positive reports": f["nrep"]} if f["pos"] else {}),
                   **f["extra"], "Municipality": f["muni"], "Barangay": f["brgy"], "Latitude": f["raw_lat"],
                   "Longitude": f["raw_lon"], "Risk level": f["level"], "Risk score": f["score"], "DA/BAI zone": f["zone"],
                   "Distance to nearest case (km)": f["km"], "Swine population": f["pop"],
                   "Farm density": f["dens"], "Biosecurity L1 compliant": f["bio"], "Nearest road (km)": f["road_km"],
                   "Access road nearby": f["access"], "Cluster size": f["csize"], "Cases in cluster": f["ccases"],
                   "Action": f["action"]}
            tbl = "".join(f"<tr><td><b>{escape(str(k))}</b></td><td>{escape(str(v))}</td></tr>"
                          for k, v in det.items() if v not in (None, ""))
            out.append(f'<Placemark><name>#{f["id"]} {escape(str(f["brgy"] or ""))}</name>'
                       f'<styleUrl>#{"sPos" if f["pos"] else "s" + lv}</styleUrl>'
                       f'<description><![CDATA[<table>{tbl}</table>]]></description>'
                       f'<Point><coordinates>{f["lon"]},{f["lat"]},0</coordinates></Point></Placemark>')
        out.append('</Folder>')
    out.append('</Document></kml>')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="farm_risk_latest.csv")
    ap.add_argument("--out", default="asf_risk_map.html")
    ap.add_argument("--kml", default="asf_risk_map.kml")
    ap.add_argument("--env"); ap.add_argument("--db-url"); ap.add_argument("--farms")
    ap.add_argument("--cases", help="CSV with farm_id, first_positive (or onset), positive_reports")
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--as-of", default=None, help="label only; default = today")
    a = ap.parse_args()

    df = pd.read_csv(a.csv)
    for need in ("id", "latitude", "longitude", "risk_level"):
        if need not in df.columns:
            raise SystemExit(f"{a.csv} has no '{need}' column - run the latest trainModel.py first.")
    eng = get_engine(a)
    recs = build_records(df, load_registry(a, eng), load_cases(a, eng))
    cases = [dict(id=r["id"], lat=r["lat"], lon=r["lon"]) for r in recs if r["pos"] and r["ok"]]
    meta = dict(as_of=a.as_of or datetime.today().strftime("%Y-%m-%d"),
                method=str(df["method"].iloc[0]) if "method" in df.columns else "n/a")
    write_html(recs, cases, meta, a.out)
    write_kml(recs, cases, meta, a.kml)

    n_ok = sum(r["ok"] for r in recs)
    print(f"Farms: {len(recs)} | pinned on the map: {n_ok} | not placeable (no usable coordinates): {len(recs) - n_ok}")
    print("By level:", pd.Series([r["level"] for r in recs]).value_counts().to_dict())
    print(f"ASF-positive case pins (purple, always visible) and zone rings: {len(cases)} "
          f"of {sum(r['pos'] for r in recs)} confirmed positive farms")
    extra_cols = sorted({k for r in recs for k in r["extra"]})
    print("Farmer detail fields in popups:", extra_cols if extra_cols else "none (CSV only - use --env / --db-url)")
    print(f"Saved {a.out} (open in a browser) and {a.kml} (open in Google Earth)")


if __name__ == "__main__":
    main()