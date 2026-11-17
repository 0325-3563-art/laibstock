// import React, { useState } from "react";

type RiskRow = {
  id:number;
  municipality: string;
  barangay: string;
  latitude: number;   
  longitude: number;  
  risk_level: "Low" | "Moderate" | "High" | "Safe";
  risk_score?: number;         
  zoning?: string;             
};



function RiskTable() {
  const [riskData, setRiskData] = useState<RiskRow[]>([]);
  const [periodType, setPeriodType] = useState("month");
  const [periodValue, setPeriodValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [riskFilter, setRiskFilter] = useState<string>("All");



  const fetchRiskSummary = async () => {
   let url: string;

  if (periodType === "year") {
    if (!startDate || !endDate) {
      alert("Please select start and end dates");
      return;
    }
    url = `http://localhost:8000/ml-risk/summary/year?start_date=${startDate}&end_date=${endDate}`;
  } else {
    if (!periodValue) {
      alert("Please select a period value");
      return;
    }
    url = `http://localhost:8000/ml-risk/summary/${periodType}/${periodValue}`;
  }

try {
    const res = await fetch(url);
    const data = await res.json();
    console.log("Fetched data:", data);

    if (Array.isArray(data)) {
      setRiskData(data);
    } else if (data?.error) {
      alert(data.error);
      setRiskData([]);
    } else {
      alert("Backend returned null or unexpected format");
      setRiskData([]);
    }
  } catch (err) {
    console.error("Error fetching risk data:", err);
    alert("Failed to fetch risk summary");
    setRiskData([]);
  }
};
  
  // Helper to style risk levels

  const getRiskBadge = (level:string) => {
    let color:string;
    switch (level) {
      case "Low":
        color = "green";
        break;
      case "Moderate":
        color = "orange";
        break;
      case "High":
        color = "red";
        break;
      default:
        color = "gray";
    }
    return (
      <span style={{
        backgroundColor: color,
        color: "white",
        padding: "4px 8px",
        borderRadius: "6px",
        fontWeight: "bold",
      }}>
        {level}
      </span>
    );
  };

// const countUniqueFarms = (data: RiskRow[], level: string) => {
  // const farms = data
    // .filter((r) => r.risk_level === level)
    // .map((r) => r.id); // ✅ use farm id
  // return new Set(farms).size; // ✅ ensures uniqueness
// };  


 const summaryCounts = {
  high: riskData.filter((r) => r.risk_level === "High").length,
  moderate: riskData.filter((r) => r.risk_level === "Moderate").length,
  low: riskData.filter((r) => r.risk_level === "Low").length,
 };


const filteredData =
  riskFilter === "All"
    ? riskData
    : riskData.filter((row) => row.risk_level === riskFilter);

  return (
    <div>
      <h2>ASF Risk Analysis</h2>
        {/* Period Type Selector */}
      <label>
        Period Type:
        <select value={periodType} onChange={(e) => { 
          setPeriodType(e.target.value); 
          setPeriodValue(""); 
          setStartDate("");
          setEndDate("");
        }}>
          <option value="month">Monthly</option>
          <option value="quarter">Quarterly</option>
          <option value="semi_annual">Semi-Annual</option>
          <option value="year">Annual</option>
        </select>
      </label>

      {/* Dynamic Input based on periodType */}
      {periodType === "month" && (
        <label>
          Month & Year:
          <input
            type="month"
            value={periodValue}
            onChange={(e) =>{  const raw = e.target.value;
        const normalized = raw.slice(0, 7); // siguraduhin na YYYY-MM lang
        setPeriodValue(normalized);
        console.log("Selected periodValue:", normalized);}}
           defaultValue={`${new Date().getFullYear()}-01`}
          />
        </label>
      )}

      {periodType === "quarter" && (
  <div>
    <label>
      Year:
      <input
        type="number"
        value={periodValue.slice(0,4) || new Date().getFullYear()}
        onChange={(e) => {
          const year = e.target.value;
          const quarter = periodValue.slice(4) || "Q1";
          setPeriodValue(`${year}${quarter}`);
        }}
      />
    </label>

    <label style={{ marginLeft: "20px" }}>
      Quarter:
      <select
        value={periodValue.slice(4)}
        onChange={(e) => {
          const year = periodValue.slice(0,4) || new Date().getFullYear();
          setPeriodValue(`${year}${e.target.value}`);
        }}
      >
      <option value="Q1">Quarter 1</option>
      <option value="Q2">Quarter 2</option>
      <option value="Q3">Quarter 3</option>
      <option value="Q4">Quarter 4</option>
      </select>
    </label>
  </div>
)}

{periodType === "semi_annual" && (
  <div>
    <label>
      Year:
      <input
        type="number"
        value={periodValue.slice(0,4) || new Date().getFullYear()}
        onChange={(e) => {
          const year = e.target.value;
          const semi = periodValue.split("-S")[1] || "1";
          setPeriodValue(`${year}-S${semi}`);
        }}
      />
    </label>

    <label style={{ marginLeft: "20px" }}>
   Semi-Annual:
      <select
        value={periodValue.split("-S")[1] || ""}
        onChange={(e) => {
          const year = periodValue.slice(0,4) || new Date().getFullYear();
          setPeriodValue(`${year}-S${e.target.value}`);
        }}
      >
        <option value="1">First Semi-Annual (Jan–Jun)</option>
        <option value="2">Second Semi-Annual (Jul–Dec)</option>
      </select>
    </label>
  </div>
)}
      {periodType === "year" && (
        <div>
          <label>
            Start Date:
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label style={{ marginLeft: "20px" }}>
            End Date:
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
        </div>
      )}

      <button onClick={fetchRiskSummary}>Fetch Risk Summary</button>
   
      {/* Summary counters */}
    <div style={{ display: "flex", gap: "1rem", marginTop: "1rem", marginBottom: "1rem",justifyContent: "center" }}>
      <div onClick={() => setRiskFilter("High")} style={{ backgroundColor: "red", color: "white", padding: "0.5rem 1rem", borderRadius: "8px", cursor: "pointer", boxShadow: riskFilter === "High" ? "0 0 10px rgba(0,0,0,0.5)" : "none" }}>
        🔴 High Risk: {summaryCounts.high}
      </div>
      <div onClick={() => setRiskFilter("Moderate")} style={{ backgroundColor: "orange", color: "white", padding: "0.5rem 1rem", borderRadius: "8px", cursor: "pointer", boxShadow: riskFilter === "Medium" ? "0 0 10px rgba(0,0,0,0.5)" : "none" }}>
        🟠 Moderate Risk: {summaryCounts.moderate}
      </div>
      <div onClick={() => setRiskFilter("Low")} style={{ backgroundColor: "green", color: "white", padding: "0.5rem 1rem", borderRadius: "8px", cursor: "pointer", boxShadow: riskFilter === "Low" ? "0 0 10px rgba(0,0,0,0.5)" : "none" }}>
        🟢 Low Risk: {summaryCounts.low}
      </div>
    </div>

    {/* Dropdown filter */}
    <label style={{ marginRight: "1rem" }}>Filter by Risk Level:</label>
    <select
      value={riskFilter}
      onChange={(e) => setRiskFilter(e.target.value)}
      style={{ marginBottom: "1rem" }}
    >
      <option value="All">All</option>
      <option value="High">High</option>
      <option value="Moderate">Moderate</option>
      <option value="Low">Low</option>
    </select>

    {/* Risk Table */}
    <table border={1} cellPadding={8} style={{ width: "100%", marginTop: "1rem" }}>
      <thead>
        <tr>
          <th>Municipality</th>
          <th>Barangay</th>
          <th>Latitude</th>
          <th>Longitude</th>
          <th>Risk Level</th>
          <th>Risk Score</th>
          <th>Zoning</th>
        </tr>
      </thead>
      <tbody>
        {Array.isArray(filteredData) &&
          filteredData.map((row, idx) => (
            <tr key={idx}>
              <td>{row.municipality}</td>
              <td>{row.barangay}</td>
               <td>{row.latitude}</td>
              <td>{row.longitude}</td>
              <td>{getRiskBadge(row.risk_level)}</td>
              <td>{row.risk_score ?? "-"}</td>
              <td>{row.zoning ?? "-"}</td>
            </tr>
          ))}
      </tbody>
    </table>
  </div>
);
}

export default RiskTable;
