import React, { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const green900 = "#0b3d2e";
const green700 = "#1e7a52";
const ink = "#1f2937";
const muted = "#6b7280";
const line = "#e5e7eb";

const Login: React.FC = () => {
  const { role, loginFarmer, loginStaff } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from || "/ml-map";

  const [tab, setTab] = useState<"farmer" | "staff">("farmer");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  if (role) return <Navigate to={from} replace />;

  const submitStaff = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await loginStaff(username.trim(), password);
    if (ok) navigate(from, { replace: true });
    else setError("Wrong username or password. Check both and try again.");
  };

  const switchTab = (next: "farmer" | "staff") => {
    setTab(next);
    setError("");
  };

  const primaryBtn: React.CSSProperties = {
    width: "100%",
    padding: "0.75rem",
    border: "none",
    borderRadius: 10,
    background: green900,
    color: "#fff",
    fontSize: "1rem",
    fontWeight: 600,
    cursor: "pointer",
  };

  const label: React.CSSProperties = {
    display: "block",
    fontSize: "0.9rem",
    fontWeight: 600,
    color: ink,
    marginBottom: "1rem",
  };

  const input: React.CSSProperties = {
    display: "block",
    width: "100%",
    boxSizing: "border-box",
    marginTop: "0.35rem",
    padding: "0.65rem 0.75rem",
    border: `1px solid ${line}`,
    borderRadius: 8,
    fontSize: "1rem",
    background: "#fff",
    color: ink,
  };

  return (
    <div
      style={{
        maxWidth: 440,
        margin: "1rem auto",
        padding: "1.75rem",
        background: "#fff",
        border: `1px solid ${line}`,
        borderRadius: 14,
      }}
    >
      <h2 style={{ margin: "0 0 0.25rem", fontSize: "1.3rem", color: ink }}>
        Log in to view the map
      </h2>
      <p style={{ margin: "0 0 1.25rem", color: muted, fontSize: "0.95rem" }}>
        Choose how you want to continue.
      </p>

      {/* Segmented toggle, same style as the dashboard */}
      <div
        role="tablist"
        style={{
          display: "flex",
          background: "#f1f5f3",
          borderRadius: 10,
          padding: 3,
          marginBottom: "1.5rem",
        }}
      >
        {(["farmer", "staff"] as const).map((t) => {
          const active = tab === t;
          return (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => switchTab(t)}
              style={{
                flex: 1,
                padding: "0.55rem",
                border: "none",
                borderRadius: 8,
                cursor: "pointer",
                fontSize: "0.95rem",
                fontWeight: active ? 600 : 400,
                background: active ? "#fff" : "transparent",
                color: active ? green900 : muted,
                boxShadow: active ? "0 1px 2px rgba(0,0,0,0.12)" : "none",
              }}
            >
              {t === "farmer" ? "Farmer" : "MAO staff"}
            </button>
          );
        })}
      </div>

      {tab === "farmer" ? (
        <>
          <div
            style={{
              background: "#e3f1ea",
              borderLeft: `4px solid ${green700}`,
              borderRadius: 8,
              padding: "0.75rem 1rem",
              color: green900,
              fontSize: "0.95rem",
              marginBottom: "1.25rem",
            }}
          >
            Farmers can view the map. Farmer names and contact numbers are hidden.
          </div>
          <button
            type="button"
            style={primaryBtn}
            onClick={() => {
              loginFarmer();
              navigate(from, { replace: true });
            }}
          >
            View map
          </button>
        </>
      ) : (
        <form onSubmit={submitStaff}>
          <label style={label}>
            Username
            <input
              style={input}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label style={label}>
            Password
            <input
              style={input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button type="submit" style={primaryBtn}>
            Log in as staff
          </button>
          <small style={{ display: "block", marginTop: 12, color: muted }}>
            Demo: mao_staff / Mao@2026
          </small>
        </form>
      )}

      {error && (
        <p
          role="alert"
          style={{
            marginTop: "1rem",
            padding: "0.65rem 0.85rem",
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: 8,
            color: "#b91c1c",
            fontSize: "0.95rem",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
};

export default Login;