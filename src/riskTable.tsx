import React, { useEffect, useState } from "react";

const API_URL = "http://localhost:8000";

type RiskRow = {
  id: number;
  municipality: string;
  barangay: string;
  latitude: number | null;
  longitude: number | null;
  risk_level: "Low" | "Moderate" | "High";
  risk_score: number | null;
  zoning: string | null;
  confirmed_positive: number;
  new_case_in_period: number;
  method: "rule-based" | "supervised";
};

type MonthlyCount = {
  month: string;
  new_cases: number;
  cumulative: number;
  positive_reports: number;
  cumulative_reports: number;
};

const now = new Date();
const thisYear = now.getFullYear();
const thisMonth = `${thisYear}-${String(now.getMonth() + 1).padStart(2, "0")}`;
const thisQuarter = `Q${Math.floor(now.getMonth() / 3) + 1}`;
const thisSemi = now.getMonth() < 6 ? "1" : "2";
const today = now.toISOString().slice(0, 10);

/* ------------------------------------------------------------ theme (same as dashboard) */
const c = {
  green900: "#0b3d2e",
  green700: "#1e7a52",
  green100: "#e3f1ea",
  amber700: "#b45309",
  amber100: "#fef3c7",
  red700: "#b91c1c",
  red600: "#dc2626",
  red50: "#fef2f2",
  red200: "#fecaca",
  ink: "#1f2937",
  muted: "#6b7280",
  line: "#e5e7eb",
};

// text color, soft background, accent color
const RISK_STYLE: Record<string, { fg: string; bg: string; accent: string }> = {
  High: { fg: c.red700, bg: c.red50, accent: c.red600 },
  Moderate: { fg: c.amber700, bg: c.amber100, accent: "#d97706" },
  Low: { fg: "#166534", bg: c.green100, accent: c.green700 },
};

const card: React.CSSProperties = {
  background: "#fff",
  border: `1px solid ${c.line}`,
  borderRadius: 14,
  padding: "1.25rem 1.5rem",
  marginBottom: "1.25rem",
};
const sectionTitle: React.CSSProperties = { margin: "0 0 1rem", fontSize: "1.1rem", color: c.ink };
const labelStyle: React.CSSProperties = { fontSize: "0.9rem", fontWeight: 600, color: c.ink };
const control: React.CSSProperties = {
  display: "block",
  marginTop: "0.35rem",
  padding: "0.55rem 0.7rem",
  border: `1px solid ${c.line}`,
  borderRadius: 8,
  fontSize: "0.95rem",
  fontFamily: "inherit",
  background: "#fff",
  color: c.ink,
  boxSizing: "border-box",
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
  position: "sticky",
  top: 0,
};
const td: React.CSSProperties = {
  padding: "0.6rem 0.75rem",
  fontSize: "0.92rem",
  color: c.ink,
  borderBottom: `1px solid ${c.line}`,
};

function Tile({
  label,
  value,
  sub,
  accent,
  onClick,
  active,
  title,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent: string;
  onClick?: () => void;
  active?: boolean;
  title?: string;
}) {
  const clickable = !!onClick;
  return (
    <div
      onClick={onClick}
      title={title}
      role={clickable ? "button" : undefined}
      aria-pressed={clickable ? !!active : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={(e) => {
        if (clickable && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick?.();
        }
      }}
      style={{
        background: "#fff",
        border: `1px solid ${active ? accent : c.line}`,
        borderLeft: `6px solid ${accent}`,
        borderRadius: 12,
        padding: "0.85rem 1rem",
        cursor: clickable ? "pointer" : "default",
        boxShadow: active ? `0 0 0 3px ${accent}33` : "none",
      }}
    >
      <div style={{ fontSize: "0.85rem", color: c.muted }}>{label}</div>
      <div style={{ fontSize: "1.7rem", fontWeight: 700, color: c.ink, lineHeight: 1.2 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: "0.82rem", color: c.muted }}>{sub}</div>}
    </div>
  );
}

function RiskTable() {
  const [riskData, setRiskData] = useState<RiskRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [riskFilter, setRiskFilter] = useState<string>("All");
  const [monthlyCounts, setMonthlyCounts] = useState<MonthlyCount[]>([]);
  const [fetchedRange, setFetchedRange] = useState<[string, string] | null>(null);
  const [error, setError] = useState("");

  // Monthly + cumulative ASF case counts (independent of the selected period)
  const loadCounts = () =>
    fetch(`${API_URL}/ml-risk/case-counts`)
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setMonthlyCounts(Array.isArray(d) ? d : []))
      .catch(() => setMonthlyCounts([]));

  useEffect(() => {
    loadCounts();
  }, []);

  // Period inputs: every control has a real default, so the value shown is the value sent
  const [periodType, setPeriodType] = useState("month");
  const [month, setMonth] = useState(thisMonth);
  const [year, setYear] = useState<number>(thisYear);
  const [quarter, setQuarter] = useState(thisQuarter);
  const [semi, setSemi] = useState(thisSemi);
  const [startDate, setStartDate] = useState(`${thisYear}-01-01`);
  const [endDate, setEndDate] = useState(today);

  const buildUrl = (): string | null => {
    switch (periodType) {
      case "month":
        return month ? `${API_URL}/ml-risk/summary/month/${month}` : null;
      case "quarter":
        return `${API_URL}/ml-risk/summary/quarter/${year}${quarter}`;
      case "semi_annual":
        return `${API_URL}/ml-risk/summary/semi_annual/${year}-S${semi}`;
      case "year":
        return startDate && endDate
          ? `${API_URL}/ml-risk/summary/year?start_date=${startDate}&end_date=${endDate}`
          : null;
      default:
        return null;
    }
  };

  // First and last month (YYYY-MM) covered by the current selection
  const selectedMonthRange = (): [string, string] => {
    const mm = (n: number) => String(n).padStart(2, "0");
    if (periodType === "month") return [month, month];
    if (periodType === "quarter") {
      const first = (Number(quarter.slice(1)) - 1) * 3 + 1;
      return [`${year}-${mm(first)}`, `${year}-${mm(first + 2)}`];
    }
    if (periodType === "semi_annual") {
      return semi === "1" ? [`${year}-01`, `${year}-06`] : [`${year}-07`, `${year}-12`];
    }
    return [startDate.slice(0, 7), endDate.slice(0, 7)];
  };

  const fetchRiskSummary = async () => {
    setError("");
    const url = buildUrl();
    if (!url) {
      setError("Please complete the period selection.");
      return;
    }
    setLoading(true);
    setFetchedRange(selectedMonthRange());
    loadCounts(); // new reports show up without reloading the page
    try {
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) {
        setError(typeof data?.detail === "string" ? data.detail : "Request failed.");
        setRiskData([]);
      } else if (Array.isArray(data)) {
        setRiskData(data);
      } else {
        setError("Unexpected response format from the server.");
        setRiskData([]);
      }
    } catch (err) {
      console.error("Error fetching risk data:", err);
      setError("Failed to fetch the risk summary.");
      setRiskData([]);
    } finally {
      setLoading(false);
    }
  };

  const getRiskBadge = (level: string) => {
    const s = RISK_STYLE[level] ?? { fg: c.muted, bg: c.line, accent: c.muted };
    return (
      <span
        style={{
          background: s.bg,
          color: s.fg,
          padding: "0.2rem 0.7rem",
          borderRadius: 999,
          fontWeight: 600,
          fontSize: "0.85rem",
        }}
      >
        {level}
      </span>
    );
  };

  // Count unique farms per level
  const countUniqueFarms = (level: string) =>
    new Set(riskData.filter((r) => r.risk_level === level).map((r) => r.id)).size;

  const summaryCounts = {
    high: countUniqueFarms("High"),
    moderate: countUniqueFarms("Moderate"),
    low: countUniqueFarms("Low"),
    confirmedTotal: new Set(riskData.filter((r) => r.confirmed_positive === 1).map((r) => r.id)).size,
    newInPeriod: new Set(riskData.filter((r) => r.new_case_in_period === 1).map((r) => r.id)).size,
  };

  const reportsInPeriod = fetchedRange
    ? monthlyCounts
        .filter((m) => m.month >= fetchedRange[0] && m.month <= fetchedRange[1])
        .reduce((sum, m) => sum + m.positive_reports, 0)
    : 0;

  const cumulativeCases = fetchedRange
    ? monthlyCounts
        .filter((m) => m.month <= fetchedRange[1])
        .reduce((sum, m) => sum + m.positive_reports, 0)
    : 0;

  const method = riskData[0]?.method;

  const filteredData = (riskFilter === "All"
    ? riskData
    : riskData.filter((row) => row.risk_level === riskFilter)
  )
    .slice()
    .sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0));

  // Clicking the active tile clears the filter
  const toggleFilter = (level: string) => setRiskFilter(riskFilter === level ? "All" : level);

  const inSelectedRange = (m: string) =>
    !!fetchedRange && m >= fetchedRange[0] && m <= fetchedRange[1];

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* Period selection */}
      <section style={card}>
        <h2 style={sectionTitle}>Assessment period</h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem 1.25rem", alignItems: "end" }}>
          <label style={labelStyle}>
            Period type
            <select
              style={control}
              value={periodType}
              onChange={(e) => setPeriodType(e.target.value)}
            >
              <option value="month">Monthly</option>
              <option value="quarter">Quarterly</option>
              <option value="semi_annual">Semi-annual</option>
              <option value="year">Annual / date range</option>
            </select>
          </label>

          {periodType === "month" && (
            <label style={labelStyle}>
              Month and year
              <input
                style={control}
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value.slice(0, 7))}
              />
            </label>
          )}

          {(periodType === "quarter" || periodType === "semi_annual") && (
            <>
              <label style={labelStyle}>
                Year
                <input
                  style={{ ...control, width: 110 }}
                  type="number"
                  value={year}
                  min={2000}
                  max={2100}
                  onChange={(e) => setYear(Number(e.target.value) || thisYear)}
                />
              </label>
              {periodType === "quarter" ? (
                <label style={labelStyle}>
                  Quarter
                  <select style={control} value={quarter} onChange={(e) => setQuarter(e.target.value)}>
                    <option value="Q1">Quarter 1</option>
                    <option value="Q2">Quarter 2</option>
                    <option value="Q3">Quarter 3</option>
                    <option value="Q4">Quarter 4</option>
                  </select>
                </label>
              ) : (
                <label style={labelStyle}>
                  Half of the year
                  <select style={control} value={semi} onChange={(e) => setSemi(e.target.value)}>
                    <option value="1">First (Jan–Jun)</option>
                    <option value="2">Second (Jul–Dec)</option>
                  </select>
                </label>
              )}
            </>
          )}

          {periodType === "year" && (
            <>
              <label style={labelStyle}>
                Start date
                <input
                  style={control}
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </label>
              <label style={labelStyle}>
                End date (risk is assessed as of this date)
                <input
                  style={control}
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </label>
            </>
          )}

          <button
            type="button"
            onClick={fetchRiskSummary}
            disabled={loading}
            style={{
              padding: "0.65rem 1.4rem",
              border: "none",
              borderRadius: 10,
              background: c.green900,
              color: "#fff",
              fontSize: "0.97rem",
              fontWeight: 600,
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? "Loading..." : "Fetch risk summary"}
          </button>
        </div>

        {error && (
          <p
            role="alert"
            style={{
              margin: "1rem 0 0",
              padding: "0.65rem 0.9rem",
              borderRadius: 8,
              background: c.red50,
              border: `1px solid ${c.red200}`,
              color: c.red700,
            }}
          >
            {error}
          </p>
        )}
      </section>

      {/* Which engine produced these numbers */}
      {method && (
        <div
          style={{
            background: "#eef4ff",
            borderLeft: "5px solid #3b6fd4",
            color: "#1e3a8a",
            borderRadius: 10,
            padding: "0.8rem 1rem",
            marginBottom: "1.25rem",
            fontSize: "0.95rem",
          }}
        >
          {method === "rule-based"
            ? "Method: rule-based risk index (not enough confirmed ASF cases yet to train a model). Scores are expert-weighted, not predicted probabilities."
            : "Method: machine-learning model trained on confirmed ASF cases. Score = predicted probability (%) of a new case within 30 days."}
        </div>
      )}

      {/* Summary tiles */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
          gap: "0.9rem",
          marginBottom: "1.25rem",
        }}
      >
        <Tile
          label="High risk"
          value={summaryCounts.high}
          accent={RISK_STYLE.High.accent}
          active={riskFilter === "High"}
          onClick={() => toggleFilter("High")}
          title="Click to filter the table"
        />
        <Tile
          label="Moderate risk"
          value={summaryCounts.moderate}
          accent={RISK_STYLE.Moderate.accent}
          active={riskFilter === "Moderate"}
          onClick={() => toggleFilter("Moderate")}
          title="Click to filter the table"
        />
        <Tile
          label="Low risk"
          value={summaryCounts.low}
          accent={RISK_STYLE.Low.accent}
          active={riskFilter === "Low"}
          onClick={() => toggleFilter("Low")}
          title="Click to filter the table"
        />
        <Tile
          label="New ASF cases in period"
          value={reportsInPeriod}
          accent="#6b7280"
          title="Every positive report in the period, including repeat reports on the same farm"
        />
        <Tile
          label="Cumulative ASF cases"
          value={cumulativeCases}
          sub="up to end of period"
          accent="#6b7280"
        />
        <Tile
          label="Farms affected"
          value={summaryCounts.confirmedTotal}
          sub={`new in period: ${summaryCounts.newInPeriod}`}
          accent="#6b7280"
          title="Distinct farms with a confirmed case; this is what drives the risk map"
        />
      </div>

      {/* Risk table */}
      <section style={card}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "0.75rem",
            marginBottom: "1rem",
          }}
        >
          <h2 style={{ ...sectionTitle, margin: 0 }}>Risk by farm</h2>
          <label style={{ ...labelStyle, display: "flex", alignItems: "center", gap: "0.5rem" }}>
            Risk level
            <select
              style={{ ...control, marginTop: 0 }}
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
            >
              <option value="All">All</option>
              <option value="High">High</option>
              <option value="Moderate">Moderate</option>
              <option value="Low">Low</option>
            </select>
          </label>
        </div>

        {riskData.length > 0 && (
          <p style={{ margin: "0 0 0.75rem", color: c.muted, fontSize: "0.92rem" }}>
            Showing {filteredData.length.toLocaleString()} of {riskData.length.toLocaleString()}, highest score first
          </p>
        )}

        <div style={{ overflow: "auto", maxHeight: 520 }}>
          <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 700 }}>
            <thead>
              <tr>
                <th style={th}>Municipality</th>
                <th style={th}>Barangay</th>
                <th style={th}>Latitude</th>
                <th style={th}>Longitude</th>
                <th style={th}>Risk level</th>
                <th style={th}>Risk score</th>
                <th style={th}>Zoning</th>
              </tr>
            </thead>
            <tbody>
              {filteredData.map((row) => (
                <tr key={row.id}>
                  <td style={td}>{row.municipality}</td>
                  <td style={td}>{row.barangay}</td>
                  <td style={td}>{row.latitude ?? "-"}</td>
                  <td style={td}>{row.longitude ?? "-"}</td>
                  <td style={td}>{getRiskBadge(row.risk_level)}</td>
                  <td style={{ ...td, fontWeight: 600 }}>{row.risk_score ?? "-"}</td>
                  <td style={td}>{row.zoning ?? "-"}</td>
                </tr>
              ))}
              {!loading && filteredData.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ ...td, textAlign: "center", color: c.muted }}>
                    No data. Choose a period and click "Fetch risk summary".
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Monthly and cumulative confirmed ASF farms */}
      <section style={card}>
        <h2 style={sectionTitle}>Confirmed ASF cases per month</h2>
        <div style={{ overflow: "auto", maxHeight: 340 }}>
          <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 520 }}>
            <thead>
              <tr>
                <th style={th}>Month</th>
                <th
                  style={th}
                  title="Every positive report, including repeat reports on the same farm"
                >
                  New cases
                </th>
                <th style={th}>Cumulative cases</th>
                <th style={th} title="Farms whose first positive report is in this month">
                  New farms
                </th>
                <th style={th}>Cumulative farms</th>
              </tr>
            </thead>
            <tbody>
              {monthlyCounts.map((m) => (
                <tr
                  key={m.month}
                  style={inSelectedRange(m.month) ? { background: c.green100, fontWeight: 600 } : undefined}
                >
                  <td style={td}>{m.month}</td>
                  <td style={td}>{m.positive_reports}</td>
                  <td style={td}>{m.cumulative_reports}</td>
                  <td style={td}>{m.new_cases}</td>
                  <td style={td}>{m.cumulative}</td>
                </tr>
              ))}
              {monthlyCounts.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ ...td, textAlign: "center", color: c.muted }}>
                    No confirmed cases recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p style={{ margin: "0.75rem 0 0", color: c.muted, fontSize: "0.88rem" }}>
          Months inside the period you fetched are highlighted.
        </p>
      </section>
    </div>
  );
}

export default RiskTable;