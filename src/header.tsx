import React from "react";
import { NavLink, Link, useNavigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import "./laibstock.css";
import logo from "./assets/images/laibStock.png"

const Icon: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">{children}</svg>
);

export const NAV = [
  { to: "/dashboard", label: "Dashboard", end: true, icon: <><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></> },
  { to: "/farmer-registry", label: "Farmer Registry", icon: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" /><path d="M16 4.5a3.5 3.5 0 010 7M18 14.3c2.3.7 3.5 2.6 3.5 5.7" /></> },
  { to: "/livestock", label: "Livestock Reporting", icon: <><path d="M9 3h6l1 3h3v14H5V6h3z" /><path d="M9 12h6M9 16h4" /></> },
  { to: "/disease-reports", label: "Disease Reporting", badge: 3, icon: <><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18v.01" /></> },
  { to: "/ml-risk", label: "ML Risk Predictions", icon: <><path d="M3 17l5-5 4 4 8-9" /><path d="M15 7h5v5" /></> },
  { to: "/print", label: "Print Reports", icon: <><path d="M6 9V3h12v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><rect x="7" y="14" width="10" height="7" /></> },
  { to: "/ml-map", label: "View Map", icon: <><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z" /><path d="M9 4v14M15 6v14" /></> },
  { to: "/submit", label: "Submit Report", icon: <path d="M12 5v14M5 12h14" /> },
];

const Header: React.FC = () => {
  const { role, username, logout } = useAuth();
  const navigate = useNavigate();
  const isStaff = role === "staff";

  return (
    <aside className="lb-side">
      <div className="lb-logo">
        <img src={logo} alt="LAIBStock logo" className="lb-logo-img" />
        <b>LAIBStock</b>
        
      </div>

      <nav aria-label="Main">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => (isActive ? "active" : "")}>
            <Icon>{item.icon}</Icon>
            {item.label}
            {item.badge ? <span className="lb-badge" aria-label={`${item.badge} open reports`}>{item.badge}</span> : null}
          </NavLink>
        ))}
      </nav>

      <div className="lb-foot">
        <div className="lb-user">
          {role ? (
            <>
              <span>{isStaff ? `MAO staff: ${username}` : "Farmer"}</span>
              <button
                type="button"
                className="lb-btn"
                onClick={() => { logout(); navigate("/login"); }}
              >
                Log out
              </button>
            </>
          ) : (
            <Link to="/login" className="lb-btn lb-btn-primary">Log in</Link>
          )}
        </div>
        <div className="lb-region">Quezon Province<br />CALABARZON, Philippines</div>
      </div>
    </aside>
  );
};

export default Header;