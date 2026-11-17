import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  LayersControl,
  Circle,
  Marker,
  Popup,
  useMap,
} from "react-leaflet";
import ClusterImport from "react-leaflet-cluster";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { useAuth } from "./auth/AuthContext";

// Some bundlers hand back { default: Component } for this package; unwrap it so React gets a component.
const MarkerClusterGroup: React.ComponentType<any> = (ClusterImport as any).default ?? (ClusterImport as any);

/* ------------------------------------------------------------------ */
/* Config                                                              */
/* ------------------------------------------------------------------ */
const API_URL = "http://localhost:8000/ml-map";
const POLL_MS = 30_000; // re-fetch every 30 s so new ASF-positive cases appear automatically
const PSGC_REGION = "040000000"; // CALABARZON (Region IV-A)
const PSGC_MUNIS = `https://psgc.gitlab.io/api/regions/${PSGC_REGION}/cities-municipalities/`;

// Fields farmers must never see. Add more column names here if your registry has them.
const SENSITIVE_KEY = /farmer.?name|^name$|contact|phone|mobile|email/i;

type Level = "High" | "Moderate" | "Low" | "Unverified";

const COLORS: Record<Level | "Positive", string> = {
  High: "#d62728",
  Moderate: "#ff9f1c",
  Low: "#2ca02c",
  Unverified: "#808080",
  Positive: "#7b1fa2",
};
// Zone rings drawn around each confirmed case. Largest first so smaller ones stay on top.
// Edit this list to add or change radii.
const RING_DEFS = [
  { km: 10, label: "Surveillance Zone - 10 km", color: "#6fdc6f", fill: "#a6f0a0", fillOpacity: 0.12, weight: 1 },
  { km: 7, label: "Buffer Zone - 7 km", color: "#e6c200", fill: "#ffd400", fillOpacity: 0.2, weight: 1 },
  { km: 1, label: "Infected Zone - 1 km", color: "#c00000", fill: "#e00000", fillOpacity: 0.3, weight: 1.5 },
  { km: 0.5, label: "500 m radius", color: "#7f0000", fill: "#b00000", fillOpacity: 0.35, weight: 2 },
];

const RANK: Record<string, number> = { Unverified: 0, Low: 1, Moderate: 2, High: 3 };

interface FarmData {
  id: number;
  farmername: string;
  municipality: string;
  muniKey: string;
  barangay: string;
  latitude: number | null;
  longitude: number | null;
  risk_level: string;
  confirmed_asf_case: boolean;
  extra: Record<string, any>;
  rec: any; // raw record from /ml-map (score, zone, km, pop, dens, bio, ...)
}

interface PsgcMuni {
  code: string;
  name: string;
  key: string;
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

// "City of Lipa", "LIPA CITY", "Sto. Tomas (Capital)" -> comparable keys
const normName = (s: string = "") =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\(.*?\)/g, "")
    .replace(/\bcity of\b|\bmunicipality of\b|\bcity\b|\bmunicipality\b/g, "")
    .replace(/\bsto\.?\s/g, "santo ")
    .replace(/\bsta\.?\s/g, "santa ")
    .replace(/[^a-z0-9]/g, "");

const validCoord = (lat: any, lon: any) =>
  typeof lat === "number" &&
  typeof lon === "number" &&
  lat > 4 &&
  lat < 22 &&
  lon > 116 &&
  lon < 128;

// registry column names vary; find the farmer's name among the extra fields
const farmerName = (extra: Record<string, any> = {}) => {
  const k = Object.keys(extra).find((key) => /farmer.?name|^name$/i.test(key));
  return (k && extra[k]) || "Unknown";
};

const fmt = (v: any, d = 2, unit = "") =>
  v === null || v === undefined ? "-" : (typeof v === "number" ? v.toFixed(d) : v) + unit;

const iconCache: Record<string, L.DivIcon> = {};
const pinIcon = (color: string, positive: boolean) => {
  const key = `${color}-${positive}`;
  if (!iconCache[key]) {
    const w = positive ? 32 : 22;
    const h = Math.round(w * 1.4);
    iconCache[key] = L.divIcon({
      className: "",
      iconSize: [w, h],
      iconAnchor: [w / 2, h],
      popupAnchor: [0, -h + 4],
      html: `<svg width="${w}" height="${h}" viewBox="0 0 30 42" xmlns="http://www.w3.org/2000/svg">
        <path d="M15 1C7 1 1 7 1 15c0 11 14 26 14 26s14-15 14-26C29 7 23 1 15 1z"
              fill="${color}" stroke="#222" stroke-width="1.5"/>
        ${
          positive
            ? '<text x="15" y="21" text-anchor="middle" font-size="16" font-weight="700" fill="#fff" font-family="Arial">!</text>'
            : '<circle cx="15" cy="15" r="5" fill="#fff" opacity=".85"/>'
        }
      </svg>`,
    });
  }
  return iconCache[key];
};

const clusterIcon = (cluster: any) => {
  const markers = cluster.getAllChildMarkers();
  let worst = "Unverified";
  markers.forEach((m: any) => {
    const r = m.options.risk as string;
    if ((RANK[r] ?? 0) > (RANK[worst] ?? 0)) worst = r;
  });
  const color = COLORS[worst as Level] ?? COLORS.Unverified;
  return L.divIcon({
    html: `<div class="rm-cluster" style="background:${color}">${cluster.getChildCount()}</div>`,
    className: "",
    iconSize: [38, 38],
  });
};

/** Zooms the map to the visible farms when the municipality (or first data) changes. */
const FitToFarms: React.FC<{ points: [number, number][]; trigger: string }> = ({ points, trigger }) => {
  const map = useMap();
  const pts = useRef(points);
  pts.current = points;
  useEffect(() => {
    if (pts.current.length === 0) return;
    map.fitBounds(L.latLngBounds(pts.current), { padding: [40, 40], maxZoom: 14 });
  }, [trigger, map]);
  return null;
};

/** Tells Leaflet to redraw its tiles when the map container changes size (e.g. filter panel toggled). */
const ResizeMap: React.FC<{ trigger: boolean }> = ({ trigger }) => {
  const map = useMap();
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 50);
    return () => clearTimeout(t);
  }, [trigger, map]);
  return null;
};

const Row: React.FC<{ k: string; v: any }> = ({ k, v }) => (
  <div>
    <b>{k}:</b> {v === undefined || v === null || v === "" ? "-" : String(v)}
  </div>
);

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */
const RiskMap: React.FC = () => {
  const { role } = useAuth();
  const isStaff = role === "staff";

  const [rawFarms, setFarms] = useState<FarmData[]>([]);
  const [meta, setMeta] = useState<{ asOf: string; method: string }>({ asOf: "", method: "ML model" });
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newCaseAlert, setNewCaseAlert] = useState<string | null>(null);

  // PSGC
  const [psgc, setPsgc] = useState<PsgcMuni[]>([]);
  const [muni, setMuni] = useState<string>("ALL"); // PSGC code or "ALL"

  // filters
  const [showHigh, setShowHigh] = useState(true);
  const [showModerate, setShowModerate] = useState(true);
  const [showLow, setShowLow] = useState(true);
  const [showUnverified, setShowUnverified] = useState(true);
  const [showPositive, setShowPositive] = useState(true);
  const [showRings, setShowRings] = useState(true);
  // which individual radii are drawn (only applies while the main rings checkbox is on)
  const [ringOn, setRingOn] = useState<Record<string, boolean>>({ "0.5": false, "1": true, "7": true, "10": true });
  const [grouping, setGrouping] = useState(true);
  const [query, setQuery] = useState("");

  // filter panel open/closed (closing it gives the map the full width)
  const [panelOpen, setPanelOpen] = useState(true);

  const knownPositives = useRef<Set<number> | null>(null);

  // Farmers get a cleaned copy: no farmer name, no contact number.
  // Everything below (search, filters, popups, lists) uses `farms`, so it is hidden everywhere.
  const farms = useMemo(() => {
    if (isStaff) return rawFarms;
    return rawFarms.map((f) => {
      const extra = Object.fromEntries(
        Object.entries(f.extra).filter(([k]) => !SENSITIVE_KEY.test(k))
      );
      return { ...f, farmername: "", extra, rec: { ...f.rec, extra } };
    });
  }, [rawFarms, isStaff]);

  /* ---------- PSGC municipalities ---------- */
  useEffect(() => {
    fetch(PSGC_MUNIS)
      .then((r) => r.json())
      .then((list: any[]) =>
        setPsgc(list.map((m) => ({ code: m.code, name: m.name, key: normName(m.name) })))
      )
      .catch((e) => console.error("PSGC fetch failed:", e));
  }, []);

  /* ---------- Farm data (initial + polling) ---------- */
  const load = useCallback(async (force = false) => {
    try {
      const res = await fetch(force ? `${API_URL}?refresh=true` : API_URL, { cache: "no-store" });
      const data = await res.json();

      const list: FarmData[] = data.farms.map((f: any) => ({
        id: f.id,
        farmername: farmerName(f.extra),
        municipality: f.muni ?? "",
        muniKey: normName(f.muni),
        barangay: f.brgy ?? "",
        latitude: f.ok === false ? null : f.lat ?? null,
        longitude: f.ok === false ? null : f.lon ?? null,
        risk_level: f.level,
        confirmed_asf_case: !!f.pos,
        extra: f.extra ?? {},
        rec: f,
      }));

      // detect newly confirmed ASF-positive farms
      const positives = new Set<number>(list.filter((f) => f.confirmed_asf_case).map((f) => f.id));
      if (knownPositives.current) {
        const fresh = [...positives].filter((id) => !knownPositives.current!.has(id));
        if (fresh.length) {
          const first = list.find((f) => f.id === fresh[0]);
          setNewCaseAlert(
            `${fresh.length} new ASF-positive case${fresh.length > 1 ? "s" : ""}` +
              (first ? ` (${first.barangay}, ${first.municipality})` : "")
          );
          setTimeout(() => setNewCaseAlert(null), 10_000);
        }
      }
      knownPositives.current = positives;

      setFarms(list);
      setMeta({
        asOf: data.meta?.as_of ?? new Date().toISOString().slice(0, 10),
        method: data.meta?.method ?? "ML model",
      });
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      console.error("Error fetching risk data:", e);
      setError("Could not reach the server. Showing last known data.");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => {
      if (!document.hidden) load();
    }, POLL_MS);
    const onVisible = () => !document.hidden && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  /* ---------- Municipality options (PSGC names, with farm counts) ---------- */
  const muniOptions = useMemo(() => {
    const counts = new Map<string, number>();
    farms.forEach((f) => counts.set(f.muniKey, (counts.get(f.muniKey) ?? 0) + 1));

    const matched = new Set<string>();
    const all = psgc.map((m) => {
      matched.add(m.key);
      return { code: m.code, name: m.name, count: counts.get(m.key) ?? 0, key: m.key };
    });
    // farm municipalities that PSGC didn't match (spelling differences, etc.)
    farms.forEach((f) => {
      if (f.muniKey && !matched.has(f.muniKey)) {
        matched.add(f.muniKey);
        all.push({ code: `x-${f.muniKey}`, name: f.municipality, count: counts.get(f.muniKey) ?? 0, key: f.muniKey });
      }
    });
    const byName = (a: any, b: any) => a.name.localeCompare(b.name);
    return {
      withFarms: all.filter((m) => m.count > 0).sort(byName),
      others: all.filter((m) => m.count === 0).sort(byName),
      all,
    };
  }, [psgc, farms]);

  const selectedKey = useMemo(
    () => (muni === "ALL" ? null : muniOptions.all.find((m) => m.code === muni)?.key ?? null),
    [muni, muniOptions]
  );

  /* ---------- Derived data ---------- */
  const inMunicipality = useMemo(
    () => (selectedKey ? farms.filter((f) => f.muniKey === selectedKey) : farms),
    [farms, selectedKey]
  );

  const placed = useMemo(
    () => inMunicipality.filter((f) => validCoord(f.latitude, f.longitude)),
    [inMunicipality]
  );
  const notPlaced = useMemo(
    () => inMunicipality.filter((f) => !validCoord(f.latitude, f.longitude)),
    [inMunicipality]
  );

  const counts = useMemo(() => {
    const c = { High: 0, Moderate: 0, Low: 0, Unverified: 0, Positive: 0 };
    inMunicipality.forEach((f) => {
      if (f.risk_level in c) (c as any)[f.risk_level]++;
      if (f.confirmed_asf_case) c.Positive++;
    });
    return c;
  }, [inMunicipality]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return placed.filter((f) => {
      if (q && !`${f.id} ${f.barangay} ${f.farmername}`.toLowerCase().includes(q)) return false;
      if (f.confirmed_asf_case) return showPositive;
      if (f.risk_level === "High") return showHigh;
      if (f.risk_level === "Moderate") return showModerate;
      if (f.risk_level === "Low") return showLow;
      if (f.risk_level === "Unverified") return showUnverified;
      return true;
    });
  }, [placed, query, showHigh, showModerate, showLow, showUnverified, showPositive]);

  const positives = visible.filter((f) => f.confirmed_asf_case);
  const others = visible.filter((f) => !f.confirmed_asf_case);
  const ringFarms = placed.filter((f) => f.confirmed_asf_case);

  const fitPoints = useMemo(
    () => placed.map((f) => [f.latitude!, f.longitude!] as [number, number]),
    [placed]
  );
  const fitTrigger = `${muni}|${farms.length > 0}`;

  /* ---------- Render pieces ---------- */
  const renderPopup = (f: FarmData) => {
    const r = f.rec;
    const bio = r.bio == null ? "-" : r.bio == 1 ? "Compliant" : "NOT compliant";
    const road =
      r.road_km == null ? "-" : `${Number(r.road_km).toFixed(2)} km${r.access == 1 ? " (access road nearby)" : ""}`;
    return (
      <Popup maxWidth={320}>
        <div style={{ maxHeight: 250, overflowY: "auto", fontSize: 13 }}>
          <strong>{f.confirmed_asf_case ? `Confirmed ASF-positive farm #${f.id}` : `Farm #${f.id}`}</strong>

          {f.confirmed_asf_case && (
            <>
              <h5>ASF case</h5>
              <Row k="First confirmed positive" v={r.onset} />
              <Row k="Positive reports" v={r.nrep} />
            </>
          )}

          {Object.keys(f.extra).length > 0 && (
            <>
              <h5>Farmer details</h5>
              {Object.entries(f.extra).map(([k, v]) => (
                <Row key={k} k={k} v={v} />
              ))}
            </>
          )}
          {!isStaff && <Row k="Farmer name and contact" v="Hidden for security" />}

          <h5>Location</h5>
          <Row k="Municipality" v={r.muni} />
          <Row k="Barangay" v={r.brgy} />
          <Row k="Latitude" v={r.raw_lat} />
          <Row k="Longitude" v={r.raw_lon} />

          <h5>Risk assessment</h5>
          <div style={{ margin: "4px 0 6px", display: "flex", alignItems: "center", gap: 8 }}>
            <b>Risk level:</b>
            <span
              style={{
                display: "inline-block",
                padding: "3px 12px",
                border: `2px solid ${COLORS[r.level as Level] ?? COLORS.Unverified}`,
                borderRadius: 4,
                background: COLORS[r.level as Level] ?? COLORS.Unverified,
                color: r.level === "Moderate" ? "#1c1c1c" : "#fff",
                fontWeight: 700,
                fontSize: 14,
                letterSpacing: 0.3,
              }}
            >
              {r.level ?? "-"}
            </span>
          </div>
          <Row k="Risk score" v={r.score == null ? "-" : `${Number(r.score).toFixed(1)} / 100`} />
          <Row k="DA/BAI zone" v={r.zone} />
          <Row k="Action" v={r.action} />
          <Row k="Distance to nearest case" v={f.confirmed_asf_case ? "0 km (confirmed case)" : fmt(r.km, 2, " km")} />
          <Row k="Municipal outbreak" v={r.outbreak == null ? "-" : r.outbreak == 1 ? "Yes (2+ positive farms)" : "No"} />

          <h5>Predictors</h5>
          <Row k="Swine population" v={fmt(r.pop, 0)} />
          <Row k="Farm density" v={fmt(r.dens, 2)} />
          <Row k="Biosecurity Level 1" v={bio} />
          <Row k="Nearest access road" v={road} />
          <Row k="Road link to nearest case" v={r.rlink == null ? "-" : r.rlink == 1 ? "Yes" : "No"} />
          <Row k="Cluster" v={r.csize == null ? "-" : `${r.csize} farm(s), ${r.ccases ?? 0} case(s)`} />
        </div>
      </Popup>
    );
  };

  const marker = (f: FarmData) => {
    const color = f.confirmed_asf_case ? COLORS.Positive : COLORS[f.risk_level as Level] ?? COLORS.Unverified;
    // extra `risk` option is read by the cluster icon to colour clusters by worst risk inside
    const extra = { risk: f.risk_level } as any;
    return (
      <Marker
        key={f.id}
        position={[f.latitude!, f.longitude!]}
        icon={pinIcon(color, f.confirmed_asf_case)}
        {...extra}
      >
        {renderPopup(f)}
      </Marker>
    );
  };

  const check = (label: React.ReactNode, color: string, value: boolean, set: (v: boolean) => void, n: number, note?: string) => (
    <label className="rm-legend-row">
      <input type="checkbox" checked={value} onChange={() => set(!value)} />
      <span className="rm-dot" style={{ background: color }} />
      <b>{label}</b> <span>({n})</span>
      {note && <span className="rm-note"> - {note}</span>}
    </label>
  );

  return (
    <div className="rm-root">
      <style>{CSS}</style>

      {/* ---------------- Sidebar ---------------- */}
      <aside className={`rm-side ${panelOpen ? "" : "rm-collapsed"}`}>
        <h2 className="rm-title">ASF Risk Map</h2>
        <p className="rm-sub">
          As of {meta.asOf} | method: {meta.method} | {counts.Positive} confirmed positive farm(s)
          {selectedKey && " in this municipality"}
        </p>

        {newCaseAlert && <div className="rm-alert">New: {newCaseAlert}</div>}
        {error && <div className="rm-error">{error}</div>}

        <div className="rm-card">
          <label className="rm-field-label" htmlFor="rm-muni">City / municipality (PSGC)</label>
          <select id="rm-muni" className="rm-input" value={muni} onChange={(e) => setMuni(e.target.value)}>
            <option value="ALL">All municipalities ({farms.length})</option>
            {muniOptions.withFarms.length > 0 && (
              <optgroup label="With farms">
                {muniOptions.withFarms.map((m) => (
                  <option key={m.code} value={m.code}>
                    {m.name} ({m.count})
                  </option>
                ))}
              </optgroup>
            )}
            {muniOptions.others.length > 0 && (
              <optgroup label="No farms recorded">
                {muniOptions.others.map((m) => (
                  <option key={m.code} value={m.code}>
                    {m.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>

        <div className="rm-card">
          {check("High", COLORS.High, showHigh, setShowHigh, counts.High)}
          {check("Moderate", COLORS.Moderate, showModerate, setShowModerate, counts.Moderate)}
          {check("Low", COLORS.Low, showLow, setShowLow, counts.Low)}
          {check("Unverified", COLORS.Unverified, showUnverified, setShowUnverified, counts.Unverified, "fix coordinates")}
          {check("ASF-positive cases", COLORS.Positive, showPositive, setShowPositive, counts.Positive)}
          <p className="rm-note">Purple pin with "!" = confirmed ASF-positive farm (always shown, never grouped)</p>
        </div>

        <div className="rm-card">
          <input
            className="rm-input"
            placeholder={isStaff ? "Search id, barangay, farmer..." : "Search id or barangay..."}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <label className="rm-check">
            <input type="checkbox" checked={showRings} onChange={() => setShowRings(!showRings)} />
            DA/BAI zone rings around confirmed cases
          </label>
          <div className="rm-sub-checks">
            {[...RING_DEFS].reverse().map((d) => (
              <label key={d.km} className={`rm-check rm-sub ${showRings ? "" : "rm-off"}`}>
                <input
                  type="checkbox"
                  disabled={!showRings}
                  checked={!!ringOn[String(d.km)]}
                  onChange={() => setRingOn((prev) => ({ ...prev, [String(d.km)]: !prev[String(d.km)] }))}
                />
                <span className="rm-dot" style={{ background: d.fill, borderColor: d.color }} />
                {d.label}
              </label>
            ))}
          </div>
          <label className="rm-check">
            <input type="checkbox" checked={grouping} onChange={() => setGrouping(!grouping)} />
            Group nearby pins (click a group to zoom / spread)
          </label>
          <p className="rm-note">
            Showing {visible.length} of {inMunicipality.length} farms ({placed.length} placed on the map)
          </p>
          <p className="rm-note">
            {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : "Loading..."} - refreshes every{" "}
            {POLL_MS / 1000}s{" "}
            <button className="rm-link" onClick={() => load(true)}>Refresh now</button>
          </p>
        </div>

        <div className="rm-card">
          <b>Zones (distance from a confirmed case)</b>
          <div className="rm-zone"><span className="rm-dot" style={{ background: "#e00000" }} />Infected Zone (0-1 km)</div>
          <div className="rm-zone"><span className="rm-dot" style={{ background: "#ffd400" }} />Buffer Zone (1-7 km)</div>
          <div className="rm-zone"><span className="rm-dot" style={{ background: "#a6f0a0" }} />Surveillance Zone (7-10 km)</div>
          <div className="rm-zone"><span className="rm-dot" style={{ background: "#0a6b0a" }} />Protected/Free Zone ({">"}10 km)</div>
        </div>

        <details className="rm-card">
          <summary>Not on the map: {notPlaced.length} (no usable coordinates)</summary>
          <ul className="rm-missing">
            {notPlaced.map((f) => (
              <li key={f.id}>
                #{f.id} - {isStaff ? `${f.farmername}, ` : ""}{f.barangay}, {f.municipality}
              </li>
            ))}
          </ul>
        </details>
      </aside>

      {/* ---------------- Panel toggle ---------------- */}
      <button
        type="button"
        className="rm-toggle"
        onClick={() => setPanelOpen((o) => !o)}
        aria-label={panelOpen ? "Hide filters" : "Show filters"}
        title={panelOpen ? "Hide filters" : "Show filters"}
      >
        {panelOpen ? "\u2039" : "\u203A"}
      </button>

      {/* ---------------- Map ---------------- */}
      <MapContainer center={[13.96, 121.33]} zoom={11} className="rm-map" scrollWheelZoom>
        <ResizeMap trigger={panelOpen} />

        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Street map (Esri)">
            <TileLayer
              attribution="Tiles &copy; Esri"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Street map (CARTO)">
            <TileLayer
              attribution="&copy; OpenStreetMap contributors &copy; CARTO"
              url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Satellite (Esri)">
            <TileLayer
              attribution="Tiles &copy; Esri"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />
          </LayersControl.BaseLayer>
          <LayersControl.Overlay name="Place names">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
            />
          </LayersControl.Overlay>
        </LayersControl>

        <FitToFarms points={fitPoints} trigger={fitTrigger} />

        {/* DA/BAI rings: one circle per checked radius, largest first so the small ones stay on top */}
        {showRings &&
          RING_DEFS.filter((d) => ringOn[String(d.km)]).map((d) =>
            ringFarms.map((f) => (
              <Circle
                key={`ring-${d.km}-${f.id}`}
                center={[f.latitude!, f.longitude!]}
                radius={d.km * 1000}
                interactive={false}
                pathOptions={{ color: d.color, weight: d.weight, fillColor: d.fill, fillOpacity: d.fillOpacity }}
              />
            ))
          )}

        {/* Non-positive farms: grouped or loose */}
        {grouping ? (
          <MarkerClusterGroup
            chunkedLoading
            iconCreateFunction={clusterIcon}
            maxClusterRadius={35}
            disableClusteringAtZoom={18}
            spiderfyOnMaxZoom
            showCoverageOnHover={false}
          >
            {others.map(marker)}
          </MarkerClusterGroup>
        ) : (
          others.map(marker)
        )}

        {/* ASF-positive pins: always shown, never grouped */}
        {positives.map(marker)}
      </MapContainer>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Styles                                                              */
/* ------------------------------------------------------------------ */
const CSS = `
.lb-main:has(.rm-root){padding:0}
.rm-root{display:flex;height:100vh;background:#eef0f2;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1c1c1c}
.rm-side{width:320px;min-width:280px;overflow-y:auto;padding:14px;box-sizing:border-box}
.rm-collapsed{display:none}
.rm-map{flex:1;min-width:0;height:100%}
.rm-toggle{width:22px;border:0;border-left:1px solid #d9dce0;border-right:1px solid #d9dce0;background:#fff;color:#444;font-size:18px;cursor:pointer}
.rm-toggle:hover{background:#e3efe9}
.rm-title{margin:0 0 4px;font-size:22px}
.rm-sub{margin:0 0 12px;color:#555;font-size:14px}
.rm-card{background:#fff;border:1px solid #d9dce0;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:14px}
.rm-legend-row{display:flex;align-items:center;gap:8px;margin:6px 0;cursor:pointer}
.rm-dot{display:inline-block;width:16px;height:16px;border-radius:50%;border:1px solid rgba(0,0,0,.35);flex:none}
.rm-note{color:#667;font-size:13px;margin:6px 0 0}
.rm-check{display:flex;gap:8px;align-items:flex-start;margin:8px 0;cursor:pointer}
.rm-input{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #bbb;border-radius:6px;font-size:14px;background:#fff}
.rm-field-label{display:block;font-size:13px;color:#555;margin-bottom:4px}
.rm-zone{display:flex;align-items:center;gap:8px;margin:6px 0}
.rm-missing{margin:8px 0 0;padding-left:18px;font-size:13px;max-height:180px;overflow:auto}
.rm-alert{background:#f3e5f5;border:1px solid #7b1fa2;color:#4a148c;padding:8px 10px;border-radius:6px;margin-bottom:12px;font-size:14px}
.rm-error{background:#fdecea;border:1px solid #d62728;color:#8a1c1c;padding:8px 10px;border-radius:6px;margin-bottom:12px;font-size:13px}
.rm-link{background:none;border:none;color:#0b5cad;cursor:pointer;padding:0;font-size:13px;text-decoration:underline}
.rm-cluster{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#111;font-weight:700;font-size:13px;border:3px solid rgba(255,255,255,.65);box-shadow:0 0 0 1px rgba(0,0,0,.25);opacity:.92}
.rm-sub-checks{margin:0 0 6px 22px}
.rm-sub{margin:4px 0}
.rm-off{opacity:.45;cursor:default}
.rm-sub .rm-dot{width:12px;height:12px}
@media (max-width:800px){.rm-root{flex-direction:column;height:auto}.rm-side{width:auto}.rm-map{height:70vh}.rm-toggle{display:none}}
`;

export default RiskMap;
