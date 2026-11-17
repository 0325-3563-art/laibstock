import React from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Optional content on the right side (buttons, date, status chip...) */
  right?: React.ReactNode;
}

/**
 * Use this at the top of EVERY page (Dashboard, Farmer registry, Disease reporting, ...)
 * so the top area looks the same and never feels empty when switching pages.
 */
export default function PageHeader({ title, subtitle, right }: PageHeaderProps) {
  return (
    <header
      style={{
        position: "relative",
        overflow: "hidden",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: "1rem",
        flexWrap: "wrap",
        padding: "1.75rem 2rem",
        marginBottom: "1.5rem",
        borderRadius: 16,
        color: "#fff",
        background: "linear-gradient(120deg, #0b3d2e 0%, #14583f 60%, #1e7a52 100%)",
      }}
    >
      {/* faint contour rings, a nod to farmland maps */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          right: -80,
          top: -120,
          width: 420,
          height: 420,
          borderRadius: "50%",
          background:
            "repeating-radial-gradient(circle, rgba(255,255,255,0.09) 0 2px, transparent 2px 22px)",
          pointerEvents: "none",
        }}
      />

      <div style={{ position: "relative" }}>
        <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.01em",color: "rgba(255,255,255,0.78)" }}>
          {title}
        </h1>
        {subtitle && (
          <p style={{ margin: "0.35rem 0 0", fontSize: "0.95rem", color: "rgba(255,255,255,0.78)" }}>
            {subtitle}
          </p>
        )}
      </div>

      {right && <div style={{ position: "relative" }}>{right}</div>}
    </header>
  );
}