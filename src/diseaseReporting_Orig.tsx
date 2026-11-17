import React, { useState, useEffect } from "react";
import "./styles/diseaseReporting.css";

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

  // ✅ Submit handler
  const handleSubmit = async () => {
    if (!farmer) {
      alert("⚠️ Please select a farmer first.");
      return;
    }

    const payload = {
      farmer_id: farmer,
      technician_name: technicianName,
      disease,
      status,
      date_reported: dateReported,
      lab_result_date: labResultDate,
      remarks,
      municipality
    };

    try {
      const res = await fetch("http://localhost:8000/disease-reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error(`Server error: ${res.status}`);

      const data = await res.json();
      console.log("✅ Saved report:", data);
      alert("✅ Disease report saved successfully!");

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
      alert("❌ Failed to save disease report. Please try again.");
    }
  };

  // Helper: sort alphabetically by name
  const sortByName = <T extends { name: string }>(arr: T[]) =>
   [...arr].sort((a, b) => a.name.localeCompare(b.name));
// Load provinces once
useEffect(() => {
  fetch("http://localhost:8000/provinces", { mode: "cors" })
    .then(res => res.json())
    .then(data => {
      if (data.provinces) {
        setProvinces(sortByName(data.provinces));
      }
    });
}, []);

// Reset dependent state when province changes
useEffect(() => {
  if (!province) return;
  setMunicipality("");
  setBarangay("");
  setFarmers([]);
}, [province]);

// Fetch municipalities when province changes
useEffect(() => {
  if (!province) return;

  fetch(`http://localhost:8000/municipalities?province_code=${province}`, { mode: "cors" })
    .then(res => res.json())
    .then(data => {
      if (data.municipalities) {
        setMunicipalities(sortByName(data.municipalities));
      }
    });
}, [province]);

// Reset dependent state when municipality changes
useEffect(() => {
  if (!municipality) return;
  setBarangay("");
  setFarmers([]);
}, [municipality]);

// Fetch barangays when municipality changes
useEffect(() => {
  if (!municipality) return;

  fetch(`http://localhost:8000/barangays?municipality_code=${municipality}`, { mode: "cors" })
    .then(res => res.json())
    .then(data => {
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
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setFarmers(data.sort((a: Farmer, b: Farmer) =>
            a.farmer_name.localeCompare(b.farmer_name)
          ));
        } else {
          console.error("Farmer API error:", data);
          setFarmers([]);
        }
      });
  }
}, [province, municipality, barangay]);

  return (
    <div className="disease-reporting">
      <h2>Livestock Disease Reporting</h2>

      {/* Province dropdown */}
      <label>Province</label>
      <select value={province} onChange={e => setProvince(e.target.value)}>
        <option value="">-- Select Province --</option>
        {provinces.map(p => (
          <option key={p.code} value={p.code}>{p.name}</option>
        ))}
      </select>

      {/* Municipality dropdown */}
      <label>Municipality</label>
      <select value={municipality} onChange={e => setMunicipality(e.target.value)} disabled={!province}>
        <option value="">-- Select Municipality --</option>
        {municipalities.map(m => (
          <option key={m.code} value={m.code}>{m.name}</option>
        ))}
      </select>

      {/* Barangay dropdown */}
      <label>Barangay</label>
      <select value={barangay} onChange={e => setBarangay(e.target.value)} disabled={!municipality}>
        <option value="">-- Select Barangay --</option>
        {barangays.map(b => (
          <option key={b.code} value={b.code}>{b.name}</option>
        ))}
      </select>

      {/* Farmer dropdown */}
      <div className="farmer-dropdown">
        <label>Farmer</label>
        <select
          value={farmer}
          onChange={e => setFarmer(e.target.value)}
          disabled={!barangay}
          style={{ width: "300px" }}
        >
          <option value="">-- Select Farmer --</option>
          {farmers.map(f => (
            <option key={f.farmer_id} value={f.farmer_id}>
              {f.farmer_name}
            </option>
          ))}
        </select>
      </div>

      {/* Form fields */}
      <div className="disease-report-form">
        <div>
          <label>Technician Name</label>
          <input type="text" value={technicianName} onChange={e => setTechnicianName(e.target.value)} />
        </div>
        <div>
          <label>Disease</label>
          <input type="text" value={disease} onChange={e => setDisease(e.target.value)} />
        </div>
        <div>
          <label>Status</label>
          <select value={status} onChange={e => setStatus(e.target.value)}>
            <option value="">-- Select Status --</option>
            <option value="Positive">Positive</option>
            <option value="Negative">Negative</option>
          </select>
        </div>
        <div>
          <label>Date Reported</label>
          <input type="date" value={dateReported} onChange={e => setDateReported(e.target.value)} />
        </div>
        <div>
          <label>Lab Result Date</label>
          <input type="date" value={labResultDate} onChange={e => setLabResultDate(e.target.value)} />
        </div>
        <div>
          <label>Remarks</label>
          <textarea value={remarks} onChange={e => setRemarks(e.target.value)} />
        </div>
      </div>

      <button onClick={handleSubmit}>Save Report</button>
    </div>
  );
};

export default DiseaseReporting;
