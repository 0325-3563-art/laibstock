import React, { useState, useEffect } from "react";

// Interfaces
interface Province {
  code: string;
  name: string;
}
interface Municipality {
  code: string;
  name: string;
}
interface Barangay {
  code: string;
  name: string;
}
interface Farmer {
  farmer_id: string;
  farmer_name: string;
}

/* ------------------------------------------------------------ theme (same as dashboard) */
const c = {
  green900: "#0b3d2e",
  green700: "#1e7a52",
  green100: "#e3f1ea",
  red700: "#b91c1c",
  red600: "#dc2626",
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

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "0.9rem",
  fontWeight: 600,
  color: c.ink,
};

const controlStyle = (disabled = false): React.CSSProperties => ({
  display: "block",
  width: "100%",
  boxSizing: "border-box",
  marginTop: "0.35rem",
  padding: "0.6rem 0.7rem",
  border: `1px solid ${c.line}`,
  borderRadius: 8,
  fontSize: "0.95rem",
  fontFamily: "inherit",
  background: disabled ? "#f3f4f6" : "#fff",
  color: disabled ? c.muted : c.ink,
  cursor: disabled ? "not-allowed" : undefined,
});

const sectionTitle: React.CSSProperties = {
  margin: "0 0 1rem",
  fontSize: "1.1rem",
  color: c.ink,
};

const DiseaseReporting: React.FC = () => {
  const [province, setProvince] = useState("");
  const [municipality, setMunicipality] = useState("");
  const [barangay, setBarangay] = useState("");
  const [farmer, setFarmer] = useState("");

  const [provinces, setProvinces] = useState<Province[]>([]);
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  const [barangays, setBarangays] = useState<Barangay[]>([]);
  const [farmers, setFarmers] = useState<Farmer[]>([]);

  const [technicianName, setTechnicianName] = useState("");
  const [disease, setDisease] = useState("");
  const [status, setStatus] = useState("");
  const [dateReported, setDateReported] = useState("");
  const [labResultDate, setLabResultDate] = useState("");
  const [remarks, setRemarks] = useState("");

  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // ✅ Submit handler
  const handleSubmit = async () => {
    if (!farmer) {
      setMsg({ ok: false, text: "Please select a farmer first." });
      return;
    }

    const payload = {
      farmer_id: parseInt(farmer, 10),
      technician_name: technicianName,
      disease,
      status,
      date_reported: dateReported ? `${dateReported}T00:00:00` : null,
      lab_result_date: labResultDate ? `${labResultDate}T00:00:00` : null,
      remarks,
      municipality,
    };

    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch("http://localhost:8000/disease-reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error(`Server error: ${res.status}`);

      const data = await res.json();
      console.log("✅ Saved report:", data);
      setMsg({ ok: true, text: "Disease report saved successfully." });

      // Reset form after save
      setTechnicianName("");
      setDisease("");
      setStatus("");
      setDateReported("");
      setLabResultDate("");
      setRemarks("");
      setFarmer("");
      setBarangay("");
      setMunicipality("");
      setProvince("");
    } catch (err) {
      console.error("❌ Error saving report:", err);
      setMsg({ ok: false, text: "Failed to save the disease report. Please try again." });
    } finally {
      setSaving(false);
    }
  };

  // Helper: sort alphabetically by name
  const sortByName = <T extends { name: string }>(arr: T[]) =>
    [...arr].sort((a, b) => a.name.localeCompare(b.name));

  // Load provinces once
  useEffect(() => {
    fetch("http://localhost:8000/provinces", { mode: "cors" })
      .then((res) => res.json())
      .then((data) => {
        if (data.provinces) {
          setProvinces(sortByName(data.provinces));
        }
      });
  }, []);

  // Reset + fetch municipalities when province changes
  useEffect(() => {
    if (!province) return;
    // Reset dependent state first
    setMunicipality("");
    setBarangay("");
    setFarmers([]);

    fetch(`http://localhost:8000/municipalities?province_code=${province}`, { mode: "cors" })
      .then((res) => res.json())
      .then((data) => {
        if (data.municipalities) {
          setMunicipalities(sortByName(data.municipalities));
        }
      });
  }, [province]);

  // Reset + fetch barangays when municipality changes
  useEffect(() => {
    if (!municipality) return;

    setBarangay("");
    setFarmers([]);

    fetch(`http://localhost:8000/barangays?municipality_code=${municipality}`, { mode: "cors" })
      .then((res) => res.json())
      .then((data) => {
        if (data.barangays) {
          setBarangays(sortByName(data.barangays));
        }
      });
  }, [municipality]);

  // Fetch farmers when all three are selected
  useEffect(() => {
    if (province && municipality && barangay) {
      fetch(
        `http://localhost:8000/farmers/filter?province=${province}&municipality=${municipality}&barangay=${barangay}`,
        { mode: "cors" }
      )
        .then((res) => res.json())
        .then((data) => {
          if (Array.isArray(data)) {
            setFarmers(
              data.sort((a: Farmer, b: Farmer) => a.farmer_name.localeCompare(b.farmer_name))
            );
          } else {
            console.error("Farmer API error:", data);
            setFarmers([]);
          }
        });
    }
  }, [province, municipality, barangay]);

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      {/* Section 1: where */}
      <section style={card}>
        <h2 style={sectionTitle}>1. Farmer Profile</h2>
        <div style={grid}>
          <label style={labelStyle}>
            Province
            <select
              style={controlStyle()}
              value={province}
              onChange={(e) => setProvince(e.target.value)}
            >
              <option value="">Select province</option>
              {provinces.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>

          <label style={labelStyle}>
            Municipality
            <select
              style={controlStyle(!province)}
              value={municipality}
              onChange={(e) => setMunicipality(e.target.value)}
              disabled={!province}
            >
              <option value="">Select municipality</option>
              {municipalities.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>

          <label style={labelStyle}>
            Barangay
            <select
              style={controlStyle(!municipality)}
              value={barangay}
              onChange={(e) => setBarangay(e.target.value)}
              disabled={!municipality}
            >
              <option value="">Select barangay</option>
              {barangays.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>

          <label style={labelStyle}>
            Farmer
            <select
              style={controlStyle(!barangay)}
              value={farmer}
              onChange={(e) => setFarmer(e.target.value)}
              disabled={!barangay}
            >
              <option value="">Select farmer</option>
              {farmers.map((f) => (
                <option key={f.farmer_id} value={f.farmer_id}>
                  {f.farmer_name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {/* Section 2: what */}
      <section style={card}>
        <h2 style={sectionTitle}>2. Disease Report Details</h2>
        <div style={grid}>
          <label style={labelStyle}>
            Technician name
            <input
              type="text"
              style={controlStyle()}
              value={technicianName}
              onChange={(e) => setTechnicianName(e.target.value)}
            />
          </label>

          <label style={labelStyle}>
            Disease
            <input
              type="text"
              style={controlStyle()}
              value={disease}
              onChange={(e) => setDisease(e.target.value)}
            />
          </label>

          <div>
            <span style={labelStyle}>Lab result</span>
            <div
              role="radiogroup"
              aria-label="Lab result status"
              style={{
                display: "flex",
                background: "#f1f5f3",
                borderRadius: 10,
                padding: 3,
                marginTop: "0.35rem",
              }}
            >
              {(["Positive", "Negative"] as const).map((s) => {
                const active = status === s;
                const activeColor = s === "Positive" ? c.red700 : c.green700;
                return (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setStatus(active ? "" : s)}
                    style={{
                      flex: 1,
                      padding: "0.5rem",
                      border: "none",
                      borderRadius: 8,
                      cursor: "pointer",
                      fontSize: "0.95rem",
                      fontWeight: active ? 600 : 400,
                      background: active ? "#fff" : "transparent",
                      color: active ? activeColor : c.muted,
                      boxShadow: active ? "0 1px 2px rgba(0,0,0,0.12)" : "none",
                    }}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>

          <label style={labelStyle}>
            Date reported
            <input
              type="date"
              style={controlStyle()}
              value={dateReported}
              onChange={(e) => setDateReported(e.target.value)}
            />
          </label>

          <label style={labelStyle}>
            Lab result date
            <input
              type="date"
              style={controlStyle()}
              value={labResultDate}
              onChange={(e) => setLabResultDate(e.target.value)}
            />
          </label>
        </div>

        <label style={{ ...labelStyle, marginTop: "1rem" }}>
          Remarks
          <textarea
            rows={3}
            style={{ ...controlStyle(), resize: "vertical" }}
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
          />
        </label>

        {msg && (
          <p
            role="alert"
            style={{
              marginTop: "1rem",
              padding: "0.65rem 0.9rem",
              borderRadius: 8,
              background: msg.ok ? c.green100 : c.red50,
              border: `1px solid ${msg.ok ? "#b7dcc8" : c.red200}`,
              color: msg.ok ? c.green900 : c.red700,
            }}
          >
            {msg.text}
          </p>
        )}

        <div style={{ marginTop: "1.25rem" }}>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saving}
            style={{
              padding: "0.7rem 1.5rem",
              border: "none",
              borderRadius: 10,
              background: c.green900,
              color: "#fff",
              fontSize: "1rem",
              fontWeight: 600,
              cursor: saving ? "wait" : "pointer",
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? "Saving..." : "Save report"}
          </button>
        </div>
      </section>
    </div>
  );
};

export default DiseaseReporting;