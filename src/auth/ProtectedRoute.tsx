import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { type Role, useAuth } from "./AuthContext";

interface Props {
  children: React.ReactElement;
  allow?: Exclude<Role, null>[]; // default: any logged-in role
}

// Not logged in -> /login (remembers where they were going, e.g. /ml-map)
// Logged in but wrong role -> back to the map
const ProtectedRoute: React.FC<Props> = ({ children, allow = ["farmer", "staff"] }) => {
  const { role } = useAuth();
  const location = useLocation();

  if (!role) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (!allow.includes(role)) return <Navigate to="/ml-map" replace />;
  return children;
};

export default ProtectedRoute;