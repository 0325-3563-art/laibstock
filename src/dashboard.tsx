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
import { Bar } from "react-chartjs-2";

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

interface Outbreak {
  municipality: string;
  positive_cases: number;
  latest_report: string;
}

const API = "http://localhost:8000";

const colors = {
  green900: "#0b3d2e",
  green700: "#1e7a52",
  green100: "#e3f1ea",
  amber700: "#b45309",
  amber100: "#fef3c7",
  blue700: "#1d4ed8",
  blue100: "#dbeafe",
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
  border: `1px solid ${colors.line}`,
  borderRadius: 14,
  padding: "1.25rem 1.5rem",
};

function formatReportDate(value: string) {
  const d = new Date(value.replace(" ", "T"));
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" });
}

function StatCard({
  label,
  value,
  icon,
  tint,
  fg,
}: {
  label: string;
  value: number;
  icon: string;
  tint: string;
  fg: string;
}) {
  return (
    <div style={{ ...card, display: "flex", alignItems: "center", gap: "1rem" }}>
      <div
        aria-hidden
        style={{
          width: 52,
          height: 52,
          borderRadius: 14,
          background: tint,
          color: fg,
          display: "grid",
          placeItems: "center",
          fontSize: "1.5rem",
          flexShrink: 0,
        }}
      >
        {icon}
      </div>
      <div>
        <div style={{ fontSize: "0.9rem", color: colors.muted }}>{label}</div>
        <div style={{ fontSize: "1.9rem", fontWeight: 700, color: colors.ink, lineHeight: 1.15 }}>
          {value.toLocaleString()}
        </div>
      </div>
    </div>
  );
}

function Dashboard() {
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  const [selectedMunicipality, setSelectedMunicipality] = useState("Tiaong");
  const [viewLevel, setViewLevel] = useState<"municipality" | "barangay">("municipality");
  const [chartData, setChartData] = useState<MunicipalityData | BarangayData | null>(null);
  const [registeredFarms, setRegisteredFarms] = useState<number>(0);
  const [totalAnimals, setTotalAnimals] = useState<number>(0);
  const [reportsThisMonth, setReportsThisMonth] = useState<number>(0);
  const [outbreaks, setOutbreaks] = useState<Outbreak[]>([]);

  // Municipality list
  useEffect(() => {
    fetch(`${API}/quezon/municipalities`)
      .then((res) => res.json())
      .then((data) => setMunicipalities(data.municipalities || []))
      .catch((err) => console.error("Error fetching municipalities:", err));
  }, []);

  // Chart data (was duplicated in your original file, now only once)
  useEffect(() => {
    if (!selectedMunicipality) return;
    fetch(`${API}/swine/population?municipality=${selectedMunicipality}&level=${viewLevel}`)
      .then((res) => res.json())
      .then((data) => setChartData(data))
      .catch((err) => console.error("Error fetching swine population:", err));
  }, [selectedMunicipality, viewLevel]);

  // Dashboard numbers + outbreaks
  useEffect(() => {
    fetch(`${API}/dashboard/registered_farms`)
      .then((res) => res.json())
      .then((data) => setRegisteredFarms(data.registered_farms))
      .catch((err) => console.error("Error fetching registered farms:", err));

    fetch(`${API}/dashboard/total_animals`)
      .then((res) => res.json())
      .then((data) => setTotalAnimals(data.total_animals))
      .catch((err) => console.error("Error fetching total animals:", err));

    fetch(`${API}/dashboard/reports_this_month`)
      .then((res) => res.json())
      .then((data) => setReportsThisMonth(data.reports_this_month))
      .catch((err) => console.error("Error fetching reports this month:", err));

    fetch(`${API}/dashboard/active_outbreaks`)
      .then((res) => res.json())
      .then((data) => setOutbreaks(data))
      .catch((err) => console.error("Error fetching outbreaks:", err));
  }, []);


  const barShades = ["#1e7a52", "#2f9468", "#48ab7f", "#6cc299", "#95d6b5", "#bfe9d2"];

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      title: { display: false },
    },
    scales: {
      x: { grid: { display: false } },
      y: { beginAtZero: true, grid: { color: "#eef0f2" } },
    },
  };

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* keyframes for the alert dot; stops animating if the user prefers reduced motion */}
      <style>{`
        @keyframes asfPulse {
          0%   { box-shadow: 0 0 0 0 rgba(220,38,38,.55); }
          100% { box-shadow: 0 0 0 10px rgba(220,38,38,0); }
        }
        .asf-dot { animation: asfPulse 1.6s ease-out infinite; }
        @media (prefers-reduced-motion: reduce) { .asf-dot { animation: none; } }
        .dash-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
        @media (max-width: 800px) { .dash-stats { grid-template-columns: 1fr; } }
      `}</style>


      {/* ASF status */}
      {outbreaks.length === 0 ? (
        <div
          style={{
            background: colors.green100,
            border: "1px solid #b7dcc8",
            borderLeft: `6px solid ${colors.green700}`,
            color: colors.green900,
            borderRadius: 12,
            padding: "1rem 1.25rem",
            marginBottom: "1.5rem",
            fontWeight: 600,
          }}
        >
          ✅ No active ASF outbreaks
        </div>
      ) : (
        <div
          role="alert"
          style={{
            background: colors.red50,
            border: `1px solid ${colors.red200}`,
            borderLeft: `6px solid ${colors.red600}`,
            color: colors.red700,
            borderRadius: 12,
            padding: "1rem 1.25rem",
            marginBottom: "1.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", fontWeight: 700 }}>
            <span
              className="asf-dot"
              style={{ width: 10, height: 10, borderRadius: "50%", background: colors.red600 }}
            />
            Active ASF outbreaks
          </div>
          <div style={{ marginTop: "0.75rem", display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {outbreaks.map((o, idx) => (
              <span
                key={idx}
                style={{
                  background: "#fff",
                  border: `1px solid ${colors.red200}`,
                  borderRadius: 999,
                  padding: "0.35rem 0.85rem",
                  fontSize: "0.9rem",
                  color: colors.ink,
                }}
              >
                <strong style={{ color: colors.red700 }}>{o.municipality}</strong>
                {" · "}
                {o.positive_cases} positive {o.positive_cases === 1 ? "case" : "cases"}
                {" · last report "}
                {formatReportDate(o.latest_report)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="dash-stats">
        <StatCard
          label="Registered livestock farmers"
          value={registeredFarms}
          icon="🧑‍🌾"
          tint={colors.green100}
          fg={colors.green700}
        />
        <StatCard
          label="Total animals"
          value={totalAnimals}
          icon="🐖"
          tint={colors.amber100}
          fg={colors.amber700}
        />
        <StatCard
          label="Reports this month"
          value={reportsThisMonth}
          icon="📋"
          tint={colors.blue100}
          fg={colors.blue700}
        />
      </div>

      {/* Chart card */}
      <section style={card}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "1rem",
            marginBottom: "1rem",
          }}
        >
          <h2 style={{ margin: 0, fontSize: "1.2rem", color: colors.ink }}>
            Livestock population 
          </h2>

          <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: colors.muted }}>
              Municipality
              <select
                value={selectedMunicipality}
                onChange={(e) => setSelectedMunicipality(e.target.value)}
                style={{
                  padding: "0.4rem 0.6rem",
                  borderRadius: 8,
                  border: `1px solid ${colors.line}`,
                  background: "#fff",
                  color: colors.ink,
                  fontSize: "0.95rem",
                }}
              >
                <option value="">Select municipality</option>
                {municipalities.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>

            {/* Segmented toggle instead of loose radio buttons */}
            <div
              role="radiogroup"
              aria-label="Chart level"
              style={{ display: "inline-flex", background: "#f1f5f3", borderRadius: 10, padding: 3 }}
            >
              {(["municipality", "barangay"] as const).map((level) => {
                const active = viewLevel === level;
                return (
                  <label
                    key={level}
                    style={{
                      padding: "0.4rem 0.9rem",
                      borderRadius: 8,
                      cursor: "pointer",
                      fontSize: "0.9rem",
                      fontWeight: active ? 600 : 400,
                      background: active ? "#fff" : "transparent",
                      color: active ? colors.green900 : colors.muted,
                      boxShadow: active ? "0 1px 2px rgba(0,0,0,0.12)" : "none",
                    }}
                  >
                    <input
                      type="radio"
                      name="viewLevel"
                      value={level}
                      checked={active}
                      onChange={() => setViewLevel(level)}
                      style={{ position: "absolute", opacity: 0, pointerEvents: "none" }}
                    />
                    {level === "municipality" ? "Municipality" : "Barangay"}
                  </label>
                );
              })}
            </div>
          </div>
        </div>

        <p style={{ margin: "0 0 1rem", color: colors.muted, fontSize: "0.95rem" }}>
          {chartData?.level === "barangay"
            ? `Swine population per barangay in ${chartData.municipality}`
            : chartData
            ? `Swine population in ${chartData.municipality}`
            : "Choose a municipality to see its swine population."}
        </p>

        <div style={{ height: 340 }}>
          {chartData?.level === "municipality" && (
            <Bar
              data={{
                labels: ["Total swine"],
                datasets: [
                  {
                    label: "Swine population",
                    data: [chartData.total_swine || 0],
                    backgroundColor: colors.green700,
                    borderRadius: 8,
                    barPercentage: 0.4,
                    categoryPercentage: 0.5,
                  },
                ],
              }}
              options={chartOptions}
            />
          )}

          {chartData?.level === "barangay" && (
            <Bar
              data={{
                labels: chartData.barangays.map((b) => b.name),
                datasets: [
                  {
                    label: "Swine population",
                    data: chartData.barangays.map((b) => b.total_swine),
                    backgroundColor: chartData.barangays.map(
                      (_, i) => barShades[i % barShades.length]
                    ),
                    borderRadius: 6,
                    barPercentage: 0.7,
                    categoryPercentage: 0.8,
                  },
                ],
              }}
              options={chartOptions}
            />
          )}
        </div>
      </section>
    </div>
  );
}

export default Dashboard;