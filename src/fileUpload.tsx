import React, { useState } from "react";
import axios from "axios";

/* ------------------------------------------------------------ theme (same as dashboard) */
const c = {
  green900: "#0b3d2e",
  green700: "#1e7a52",
  green100: "#e3f1ea",
  red700: "#b91c1c",
  red50: "#fef2f2",
  red200: "#fecaca",
  ink: "#1f2937",
  muted: "#6b7280",
  line: "#e5e7eb",
};

const card: React.CSSProperties = {
  background: "#fff",
  border: `1px solid ${c.line}`,
  borderRadius: 14,
  padding: "1.25rem 1.5rem",
  marginBottom: "1.25rem",
};
const grid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
  gap: "1rem 1.25rem",
};
const sectionTitle: React.CSSProperties = { margin: "0 0 1rem", fontSize: "1.1rem", color: c.ink };
const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "0.9rem",
  fontWeight: 600,
  color: c.ink,
};
const control: React.CSSProperties = {
  display: "block",
  width: "100%",
  boxSizing: "border-box",
  marginTop: "0.35rem",
  padding: "0.6rem 0.7rem",
  border: `1px solid ${c.line}`,
  borderRadius: 8,
  fontSize: "0.95rem",
  fontFamily: "inherit",
  background: "#fff",
  color: c.ink,
};
const primaryBtn: React.CSSProperties = {
  padding: "0.7rem 1.4rem",
  border: "none",
  borderRadius: 10,
  background: c.green900,
  color: "#fff",
  fontSize: "0.98rem",
  fontWeight: 600,
  cursor: "pointer",
};
const ghostBtn: React.CSSProperties = {
  padding: "0.65rem 1.2rem",
  border: `1px solid ${c.line}`,
  borderRadius: 10,
  background: "#fff",
  color: c.ink,
  fontSize: "0.95rem",
  fontWeight: 600,
  cursor: "pointer",
};
const th: React.CSSProperties = {
  textAlign: "left",
  padding: "0.6rem 0.75rem",
  fontSize: "0.82rem",
  color: c.muted,
  fontWeight: 600,
  borderBottom: `1px solid ${c.line}`,
  whiteSpace: "nowrap",
  background: "#f9fafb",
};
const td: React.CSSProperties = {
  padding: "0.6rem 0.75rem",
  fontSize: "0.9rem",
  color: c.ink,
  borderBottom: `1px solid ${c.line}`,
  whiteSpace: "nowrap",
};


type Msg = { ok: boolean; text: string } | null;

function Message({ msg }: { msg: Msg }) {
  if (!msg) return null;
  return (
    <p
      role="alert"
      style={{
        margin: "1rem 0 0",
        padding: "0.65rem 0.9rem",
        borderRadius: 8,
        background: msg.ok ? c.green100 : c.red50,
        border: `1px solid ${msg.ok ? "#b7dcc8" : c.red200}`,
        color: msg.ok ? c.green900 : c.red700,
      }}
    >
      {msg.text}
    </p>
  );
}

// Segmented toggle used for entry mode and biosecurity level
function Segmented({
  options,
  value,
  onPick,
}: {
  options: [string, string][];
  value: string;
  onPick: (v: string) => void;
}) {
  return (
    <div
      role="radiogroup"
      style={{
        display: "inline-flex",
        background: "#f1f5f3",
        borderRadius: 10,
        padding: 3,
        marginTop: "0.35rem",
      }}
    >
      {options.map(([val, label]) => {
        const active = value === val;
        return (
          <button
            key={val}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onPick(val)}
            style={{
              padding: "0.5rem 1rem",
              border: "none",
              borderRadius: 8,
              cursor: "pointer",
              fontSize: "0.93rem",
              fontWeight: active ? 600 : 400,
              background: active ? "#fff" : "transparent",
              color: active ? c.green900 : c.muted,
              boxShadow: active ? "0 1px 2px rgba(0,0,0,0.12)" : "none",
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

const EMPTY_FORM = {
  farmer_name: "",
  municipality: "",
  barangay: "",
  province: "",
  latitude: "",
  longitude: "",
  contact_number: "",
  type_of_farm: "",
  boar: 0,
  sow: 0,
  gilts: 0,
  piglets: 0,
  grower_fattener: 0,
  total_farm_population: "",
  rsba_registered: false,
  rsba_control_number: "",
  biosecurity_level: "None",
};

function apiError(err: unknown, fallback: string) {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data?.detail;
    if (typeof d === "string") return d;
  }
  return fallback;
}

function FileUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [farmers, setFarmers] = useState<any[]>([]);
  const [formData, setFormData] = useState<any>(EMPTY_FORM);
  const [filters, setFilters] = useState({ municipality: "", barangay: "" });
  const [screen, setScreen] = useState<"registry" | "login" | "farmers">("registry");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [entryMode, setEntryMode] = useState("total");

  const [uploadMsg, setUploadMsg] = useState<Msg>(null);
  const [uploading, setUploading] = useState(false);
  const [addMsg, setAddMsg] = useState<Msg>(null);
  const [loginMsg, setLoginMsg] = useState<Msg>(null);
  const [searching, setSearching] = useState(false);
  const [filterMsg, setFilterMsg] = useState<Msg>(null);

  // Helper to reload farmers from DB
  const refreshFarmers = async () => {
    try {
      const res = await axios.get("http://localhost:8000/farmers");
      setFarmers(res.data);
    } catch (err) {
      console.error("Error refreshing farmers:", err);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) setFile(e.target.files[0]);
  };

  const handleUpload = async () => {
    if (!file) {
      setUploadMsg({ ok: false, text: "Choose an .xlsx file first." });
      return;
    }
    const formDataUpload = new FormData();
    formDataUpload.append("file", file);
    setUploading(true);
    setUploadMsg(null);
    try {
      const res = await axios.post("http://localhost:8000/upload-excel", formDataUpload, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadMsg({ ok: true, text: res.data?.message || "File uploaded successfully." });
    } catch (err) {
      console.error("Upload failed:", err);
      setUploadMsg({ ok: false, text: apiError(err, "Upload failed. Please check the file and try again.") });
    } finally {
      setUploading(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;

    setFormData((prev: any) => {
      const updated = { ...prev, [name]: type === "checkbox" ? checked : value };

      // Auto-compute total when in breakdown mode
      if (entryMode === "breakdown") {
        const { boar, sow, gilts, piglets, grower_fattener } = updated;
        updated.total_farm_population =
          (parseInt(boar as string) || 0) +
          (parseInt(sow as string) || 0) +
          (parseInt(gilts as string) || 0) +
          (parseInt(piglets as string) || 0) +
          (parseInt(grower_fattener as string) || 0);
      }
      return updated;
    });
  };

  const handleFilterChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFilters({ ...filters, [name]: value });
  };

  const viewFarmers = async (override?: { municipality: string; barangay: string }) => {
  const municipality = (override ?? filters).municipality.trim();
  const barangay = (override ?? filters).barangay.trim();

  setFilterMsg(null);

  if (barangay && !municipality) {
    setFilterMsg({ ok: false, text: "Enter a municipality to filter by barangay." });
    return;
  }

  setSearching(true);
  try {
    const res = municipality
      ? await axios.get("http://localhost:8000/farmers/search", {
          params: barangay ? { municipality, barangay } : { municipality },
        })
      : await axios.get("http://localhost:8000/farmers");
    setFarmers(res.data);
  } catch (err) {
    console.error("Error fetching farmers:", err);
    setFilterMsg({ ok: false, text: apiError(err, "Could not load farmers.") });
  } finally {
    setSearching(false);
  }
};


const clearFilters = () => {
  const empty = { municipality: "", barangay: "" };
  setFilters(empty);
  viewFarmers(empty);
};
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddMsg(null);
    try {
      const res = await axios.post("http://localhost:8000/add-farmer", formData);
      setAddMsg({ ok: true, text: res.data?.message || "Farmer added." });
      await refreshFarmers();
      setFormData(EMPTY_FORM);
    } catch (err) {
      console.error("Error adding farmer:", err);
      setAddMsg({ ok: false, text: apiError(err, "Could not add the farmer. Please check the form.") });
    }
  };

  const handleLogin = async () => {
    setLoginMsg(null);
    try {
      const res = await axios.post("http://localhost:8000/api/mao-login", { username, password });
      if (res.data.success) {
        setScreen("farmers");
        await viewFarmers();
      } else {
        setLoginMsg({ ok: false, text: "Wrong username or password." });
      }
    } catch (err) {
      setLoginMsg({ ok: false, text: "Login failed. Please try again." });
      console.error(err);
    }
  };

  // Small helper so each text field is one line below
  const field = (
    name: string,
    label: string,
    opts: { type?: string; required?: boolean; placeholder?: string } = {}
  ) => (
    <label style={labelStyle}>
      {label}
      <input
        style={control}
        name={name}
        type={opts.type || "text"}
        value={formData[name]}
        onChange={handleChange}
        required={opts.required}
        placeholder={opts.placeholder}
      />
    </label>
  );

  /* ============================== REGISTRY SCREEN ============================== */
  if (screen === "registry") {
    return (
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        {/* Excel upload */}
        <section style={card}>
          <h2 style={sectionTitle}>Upload farmer registry (Excel)</h2>
          <p style={{ margin: "0 0 1rem", color: c.muted, fontSize: "0.95rem" }}>
            Use an .xlsx file. The system will read the farms and compute density, nearest
            farm and clusters.
          </p>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
            <input
              type="file"
              accept=".xlsx"
              onChange={handleFileChange}
              style={{ fontSize: "0.95rem" }}
            />
            <button
              type="button"
              style={{ ...primaryBtn, opacity: uploading ? 0.6 : 1 }}
              onClick={handleUpload}
              disabled={uploading}
            >
              {uploading ? "Uploading..." : "Upload File"}
            </button>
          </div>
          <Message msg={uploadMsg} />
        </section>

        <div
          style={{
            textAlign: "center",
            color: c.muted,
            fontSize: "0.85rem",
            fontWeight: 600,
            letterSpacing: "0.08em",
            margin: "0 0 1.25rem",
          }}
        >
          OR ADD ONE FARMER
        </div>

        <form onSubmit={handleSubmit}>
          {/* Farmer details */}
          <section style={card}>
            <h2 style={sectionTitle}>Farmer details</h2>
            <div style={grid}>
              {field("farmer_name", "Farmer name", { required: true })}
              {field("contact_number", "Contact number")}
              {field("province", "Province", { required: true })}
              {field("municipality", "Municipality", { required: true })}
              {field("barangay", "Barangay", { required: true })}
              <label style={labelStyle}>
                Farm type
                <select
                  style={control}
                  name="type_of_farm"
                  value={formData.type_of_farm}
                  onChange={handleChange}
                >
                  <option value="">Select farm type</option>
                  <option value="Backyard">Backyard</option>
                  <option value="Commercial">Commercial</option>
                </select>
              </label>
              {field("latitude", "Latitude")}
              {field("longitude", "Longitude")}
            </div>
          </section>

          {/* Swine population */}
          <section style={card}>
            <h2 style={sectionTitle}>Swine population</h2>
            <Segmented
              value={entryMode}
              onPick={(v) => setEntryMode(v)}
              options={[
                ["total", "Total only"],
                ["breakdown", "Breakdown by category"],
              ]}
            />

            <div style={{ marginTop: "1rem" }}>
              {entryMode === "breakdown" ? (
                <>
                  <div style={grid}>
                    {(
                      [
                        ["boar", "Boar"],
                        ["sow", "Sow"],
                        ["gilts", "Gilts"],
                        ["piglets", "Piglets"],
                        ["grower_fattener", "Grower / fattener"],
                      ] as const
                    ).map(([name, label]) => (
                      <label key={name} style={labelStyle}>
                        {label}
                        <input
                          style={control}
                          name={name}
                          type="number"
                          min={0}
                          value={formData[name]}
                          onChange={handleChange}
                          onFocus={(e) => e.target.select()}
                        />
                      </label>
                    ))}
                  </div>
                  <p style={{ margin: "1rem 0 0", fontSize: "1rem" }}>
                    Total swine count:{" "}
                    <strong style={{ fontSize: "1.3rem" }}>
                      {Number(formData.total_farm_population) || 0}
                    </strong>
                  </p>
                </>
              ) : (
                <label style={{ ...labelStyle, maxWidth: 300 }}>
                  Total swine population
                  <input
                    style={control}
                    name="total_farm_population"
                    type="number"
                    min={0}
                    value={formData.total_farm_population}
                    onChange={handleChange}
                    required
                  />
                </label>
              )}
            </div>
          </section>

          {/* RSBA and biosecurity */}
          <section style={card}>
            <h2 style={sectionTitle}>Registration and biosecurity</h2>
            <div style={grid}>
              <div>
                <span style={labelStyle}>RSBA registered</span>
                <Segmented
                  value={formData.rsba_registered ? "yes" : "no"}
                  onPick={(v) => setFormData({ ...formData, rsba_registered: v === "yes" })}
                  options={[
                    ["yes", "Yes"],
                    ["no", "No"],
                  ]}
                />
              </div>
              {field("rsba_control_number", "RSBA control number")}
              <div>
                <span style={labelStyle}>Compliant to biosecurity level</span>
                <Segmented
                  value={formData.biosecurity_level}
                  onPick={(v) => setFormData({ ...formData, biosecurity_level: v })}
                  options={[
                    ["0", "Level 0"],
                    ["1", "Level 1"],
                    ["2", "Level 2"],
                  ]}
                />
              </div>
            </div>

            <Message msg={addMsg} />

            <div style={{ marginTop: "1.25rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <button type="submit" style={primaryBtn}>
                Add farmer
              </button>
              <button type="button" style={ghostBtn} onClick={() => setScreen("login")}>
                View farmers
              </button>
            </div>
          </section>
        </form>
      </div>
    );
  }

  /* ============================== LOGIN SCREEN ============================== */
  if (screen === "login") {
    return (
      <div style={{ ...card, maxWidth: 440, margin: "1rem auto" }}>
        <h2 style={{ ...sectionTitle, marginBottom: "0.25rem" }}>MAO staff login</h2>
        <p style={{ margin: "0 0 1.25rem", color: c.muted, fontSize: "0.95rem" }}>
          Farmer names and contact numbers are only shown to MAO staff.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleLogin();
          }}
        >
          <label style={{ ...labelStyle, marginBottom: "1rem" }}>
            Username
            <input
              style={control}
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label style={labelStyle}>
            Password
            <input
              style={control}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <Message msg={loginMsg} />
          <div style={{ marginTop: "1.25rem", display: "flex", gap: "0.75rem" }}>
            <button type="submit" style={{ ...primaryBtn, flex: 1 }}>
              Log in
            </button>
            <button
              type="button"
              style={ghostBtn}
              onClick={() => {
                setLoginMsg(null);
                setScreen("registry");
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    );
  }

  /* ============================== FARMERS LIST ============================== */
  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <section style={card}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "end",
            flexWrap: "wrap",
            gap: "1rem",
          }}
        >
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "end" }}>
            <label style={{ ...labelStyle, width: 200 }}>
              Municipality
              <input
                style={control}
                name="municipality"
                value={filters.municipality}
                onChange={handleFilterChange}
              />
            </label>
            <label style={{ ...labelStyle, width: 200 }}>
              Barangay
              <input
                style={control}
                name="barangay"
                value={filters.barangay}
                onChange={handleFilterChange}
              />
            </label>
            <button type="button" style={primaryBtn} onClick={() => viewFarmers()}>
            Search
            </button>
            <button type="button" style={ghostBtn} onClick={clearFilters}>
              Clear Filters
            </button>   
          </div>
          <button type="button" style={ghostBtn} onClick={() => setScreen("registry")}>
            Back to registry
          </button>
        </div>
      </section>

      <section style={card}>
        {farmers.length > 0 ? (
          <>
            <p style={{ margin: "0 0 0.75rem", color: c.muted, fontSize: "0.92rem" }}>
              {farmers.length.toLocaleString()} farmers
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ borderCollapse: "collapse", width: "100%" }}>
                <thead>
                  <tr>
                    <th style={th}>Date</th>
                    <th style={th}>Name</th>
                    <th style={th}>Municipality</th>
                    <th style={th}>Barangay</th>
                    <th style={th}>Latitude</th>
                    <th style={th}>Longitude</th>
                    <th style={th}>Contact</th>
                    <th style={th}>Farm type</th>
                    <th style={th}>Population</th>
                    <th style={th}>RSBA registered</th>
                    <th style={th}>RSBA control #</th>
                    <th style={th}>Biosecurity L1</th>
                    <th style={th}>Farm density</th>
                    <th style={th}>Nearest farm (km)</th>
                    <th style={th}>Cluster ID</th>
                  </tr>
                </thead>
                <tbody>
                  {farmers.map((f, idx) => (
                    <tr key={idx}>
                      <td style={td}>{f.date_uploaded ? f.date_uploaded.split("T")[0] : ""}</td>
                      <td style={{ ...td, fontWeight: 600 }}>{f.farmer_name}</td>
                      <td style={td}>{f.municipality}</td>
                      <td style={td}>{f.barangay}</td>
                      <td style={td}>{f.latitude}</td>
                      <td style={td}>{f.longitude}</td>
                      <td style={td}>{f.contact_number}</td>
                      <td style={td}>{f.type_of_farm}</td>
                      <td style={td}>{f.total_farm_population}</td>
                      <td style={td}>{f.rsba_registered ? "Yes" : "No"}</td>
                      <td style={td}>{f.rsba_control_number}</td>
                      <td style={td}>{f.biosecurity_level1_compliant ? "Yes" : "No"}</td>
                      <td style={td}>{f.farm_density}</td>
                      <td style={td}>{f.nearest_farm_km ? f.nearest_farm_km.toFixed(2) : ""}</td>
                      <td style={td}>{f.cluster_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p style={{ margin: 0, color: c.muted }}>No farmers found.</p>
        )}
      </section>
    </div>
  );
}

export default FileUpload;