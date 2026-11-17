import React from "react";
import { useLocation } from "react-router-dom";
import PageHeader from "./pageheader";
import { NAV } from "./header";

// One-line description shown under each page title. Edit freely.
const SUBTITLES: Record<string, string> = {
  "/dashboard": "Livestock overview for Quezon Province",
  "/farmer-registry": "Registered livestock farmers and their holdings",
  "/livestock": "Record  livestock counts",
  "/disease-reports": "MAO Staff Disease Reporting",
  "/ml-risk": "Predicted disease risk",
  "/print": "Generate printable reports",
  "/ml-map": "See reports and risk on the map",
  "/submit": "File a new report",
  "/login": "Sign in to view risk map",
};

/**
 * Put this ONCE in your layout, above <Outlet />.
 * It reads the current route, finds the matching sidebar item, and shows
 * that item's label as the page title, so no page needs its own header code.
 */
const PageBanner: React.FC = () => {
  const { pathname } = useLocation();
  const item =
  NAV.find((n) => pathname === n.to || pathname.startsWith(n.to + "/")) ??
  (pathname === "/login" ? { to: "/login", label: "Log in" } : undefined);
  if (!item) return null;

  const today = new Date().toLocaleDateString("en-PH", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <PageHeader
      title={item.label}
      subtitle={SUBTITLES[item.to]}
      right={
        <span
          style={{
            background: "rgba(255,255,255,0.14)",
            padding: "0.45rem 0.9rem",
            borderRadius: 999,
            fontSize: "0.9rem",
          }}
        >
          {today}
        </span>
      }
    />
  );
};

export default PageBanner;