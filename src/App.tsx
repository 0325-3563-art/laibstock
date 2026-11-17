import React from "react";
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import WebHeader from "./header";
import DiseaseReporting from "./diseaseReporting";
import FarmerRegistry from "./fileUpload";
import RiskTable from "./riskTable";
import RiskMap from "./riskMap1";
import Dashboard from "./dashboard";
import Login from "./pages/Login";
import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import Livestock from "./liveStock";
import PageBanner from "./pagebanner";

function App() {
  return (
    <AuthProvider>
      <Router>
        {/* Sidebar + page content side by side */}
        <div className="lb-app">
          {/* Always show the sidebar */}
          <WebHeader />

         <main className="lb-main">
  <PageBanner />
  <div style={{ padding: "1.5rem 2rem 2rem" }}>
    <Routes>
      {/* Default page: redirect root to dashboard */}
      <Route path="/" element={<Navigate to="/dashboard" replace />} />

      {/* Public */}
      <Route path="/login" element={<Login />} />

      {/* Login is only required for View Map */}
      <Route path="/ml-map" element={<ProtectedRoute><RiskMap /></ProtectedRoute>} />

      {/* Open pages (no login needed) */}
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/farmer-registry" element={<FarmerRegistry />} />
      <Route path="/livestock" element={<Livestock />} />
      {/*<Route path="/newreport" element={<NewReport />}*/}
      <Route path="/disease-reports" element={<DiseaseReporting />} />
      <Route path="/ml-risk" element={<RiskTable />} />
    </Routes>
  </div>
</main>
        </div>
      </Router>
    </AuthProvider>
  );
}

export default App;