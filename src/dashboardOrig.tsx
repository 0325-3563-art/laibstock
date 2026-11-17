import React, { useEffect, useState } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
// import { Line, Bar } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
);
interface MunicipalityData {
  level: "municipality";
  municipality: string;
  total_swine: number;
}

interface Municipality {
  code: string;
  name: string;
}
interface Barangay {
  name: string;
  total_swine: number;
}

interface BarangayData {
  level: "barangay";
  municipality: string;
  barangays: Barangay[];
}



function Dashboard() {
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  //const [barangays, setBarangays] = useState<Barangay[]>([]);
  const [selectedMunicipality, setSelectedMunicipality] = useState("");
  const [viewLevel, setViewLevel] = useState("municipality"); // radio toggle
 const [chartData, setChartData] = useState<MunicipalityData | BarangayData | null>(null);


  // Load Quezon municipalities on mount
  useEffect(() => {
    fetch("http://localhost:8000/quezon/municipalities")
      .then(res => res.json())
      .then(data => {
        console.log("Quezon municipalities:", data);
        setMunicipalities(data.municipalities || []);
      })
      .catch(err => console.error("Error fetching municipalities:", err));
  }, []);
  

  // Handle municipality selection → fetch barangays
  const handleMunicipalityChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
  const code = e.target.value;
  setSelectedMunicipality(code);
};
useEffect(() => {
  if (selectedMunicipality) {
    fetch(`http://localhost:8000/swine/population?municipality_code=${selectedMunicipality}&level=${viewLevel}`)
      .then(res => res.json())
      .then(data => setChartData(data))
      .catch(err => console.error("Error fetching swine population:", err));
  }
}, [selectedMunicipality, viewLevel]);useEffect(() => {
  if (selectedMunicipality) {
    fetch(`http://localhost:8000/swine/population?municipality=${selectedMunicipality}&level=${viewLevel}`)
      .then(res => res.json())
      .then(data => setChartData(data))
      .catch(err => console.error("Error fetching swine population:", err));
  }
}, [selectedMunicipality, viewLevel]);


  return (
 <div style={{ padding: "2rem" }}>
  <h1>Livestock Population </h1>

  {/* Municipality dropdown */}
  <label>Municipality: </label>
  <select
  value={selectedMunicipality}
  onChange={(e) => setSelectedMunicipality(e.target.value)}
>
  <option value="">-- Select Municipality --</option>
  {municipalities.map((m) => (
    <option key={m.name} value={m.name}>
      {m.name}
    </option>
  ))}
</select>

  {/* Radio buttons below dropdown */}
  <div style={{ marginTop: "1rem" }}>
    <label>
      <input
        type="radio"
        value="municipality"
        checked={viewLevel === "municipality"}
        onChange={(e) => setViewLevel(e.target.value)}
      />
      Municipality Level
    </label>

    <label style={{ marginLeft: "1rem" }}>
      <input
        type="radio"
        value="barangay"
        checked={viewLevel === "barangay"}
        onChange={(e) => setViewLevel(e.target.value)}
      />
      Barangay Level
    </label>
  </div>

{/* ✅ Step 5: Chart rendering goes here */}
<div style={{ marginTop: "2rem" }}>
  {/* Municipality level */}
  {chartData?.level === "municipality" && (
    <Bar
      data={{
        labels: ["Total Swine"],
        datasets: [
          {
            label: "Swine Population",
            data: [chartData.total_swine || 0],
            borderColor: "rgba(75,192,192,1)",
            backgroundColor: [
          "rgba(75,192,192,0.6)",
          "rgba(255,99,132,0.6)",
          "rgba(255,206,86,0.6)",
          "rgba(54,162,235,0.6)",
          "rgba(153,102,255,0.6)",
          "rgba(255,159,64,0.6)",
        ],
        barPercentage: 0.5,       // ✅ belongs here
        categoryPercentage: 0.5,  // ✅ belongs here
          },
        ],
      }}
      options={{
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: `Swine Population in ${chartData.municipality}`,
          },
        },
      }}
    />
  )}

  {/* Barangay level */}
  {chartData?.level === "barangay" && (
    <Bar
      data={{
        labels: chartData.barangays.map((b) => b.name),
        datasets: [
          {
            label: "Swine Population",
            data: chartData.barangays.map((b) => b.total_swine),
            borderColor: "rgba(75,192,192,1)",
            backgroundColor: [
          "rgba(75,192,192,0.6)",
          "rgba(255,99,132,0.6)",
          "rgba(255,206,86,0.6)",
          "rgba(54,162,235,0.6)",
          "rgba(153,102,255,0.6)",
          "rgba(255,159,64,0.6)",
        ],
        barPercentage: 0.5,       // ✅ belongs here
        categoryPercentage: 0.5,  // ✅ belongs here

          },
        ],
      }}
      options={{
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: `Swine Population per Barangay in ${chartData.municipality}`,
          },
        },
        
      }}
    />
  )}
</div>

  </div>
);
}

export default Dashboard;
