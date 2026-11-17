import React, { useEffect, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Circle, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";

interface FarmData {
  id: number;
  farmername: string;
  municipality: string;
  barangay: string;
  latitude: number | null;
  longitude: number | null;
  risk_level: string;
  confirmed_asf_case: string;
  date_uploaded?: string;
  farm_type?: string;
  population?: number;
  rsba_registered?: boolean;
  rsba_control_number?: string;
  biosecurity_level1?: boolean;
  farm_density?: number;
  nearest_farm_km?: number;
  province?: string;
  access_road_nearby?: boolean;
  nearest_road_km?: number;
  risk_score?: number;
  zone?: string;
  action?: string;
  distance_to_case?: number;
  municipal_outbreak?: string;
  swine_population?: number;
  road_link_case?: string;
  cluster?: string;
}

const RiskMap: React.FC = () => {
  const [riskData, setRiskData] = useState<FarmData[]>([]);

  // toggles
  const [showHigh, setShowHigh] = useState(true);
  const [showModerate, setShowModerate] = useState(true);
  const [showLow, setShowLow] = useState(true);
  const [showUnverified, setShowUnverified] = useState(true);
  const [showPositive, setShowPositive] = useState(true);
  const [showRings, setShowRings] = useState(true);

  useEffect(() => {
    fetch("http://localhost:8000/ml-map")
      .then((res) => res.json())
      .then((data) => {
        const farms = data.farms.map((f: any) => ({
          id: f.id,
          farmername: f.extra?.["Farmer Name"] || "Unknown",
          municipality: f.muni,
          barangay: f.brgy,
          latitude: f.lat ?? null,
          longitude: f.lon ?? null,
          risk_level: f.level,
          confirmed_asf_case: f.pos ? "Yes" : "No",
          date_uploaded: f.extra?.["Date Uploaded"],
          farm_type: f.extra?.["Type Of Farm"],
          population: f.extra?.["Total Farm Population"],
          rsba_registered: f.extra?.["Rsba Registered"],
          rsba_control_number: f.extra?.["Rsba Control Number"],
          biosecurity_level1: f.extra?.["Biosecurity Level1 Compliant"],
          farm_density: f.extra?.["Farm Density"],
          nearest_farm_km: f.extra?.["Nearest Farm Km"],
          province: f.extra?.["Province"],
          access_road_nearby: f.extra?.["Access Road Nearby"],
          nearest_road_km: f.extra?.["Nearest Road Km"],
          risk_score: f.extra?.["Risk Score"],
          zone: f.extra?.["DA/BAI Zone"],
          action: f.extra?.["Action"],
          distance_to_case: f.extra?.["Distance to nearest case"],
          municipal_outbreak: f.extra?.["Municipal outbreak"],
          swine_population: f.extra?.["Swine population"],
          road_link_case: f.extra?.["Road link to nearest case"],
          cluster: f.extra?.["Cluster"],
        }));
        setRiskData(farms);
      })
      .catch((err) => console.error("Error fetching risk data:", err));
  }, []);

  const riskColors: Record<string, string> = {
    Low: "green",
    Moderate: "orange",
    High: "red",
    Unverified: "gray",
  };

  return (
    <div style={{ display: "flex" }}>
      {/* Sidebar checkboxes */}
      <div style={{ width: "220px", padding: "10px", fontSize: "14px" }}>
        <h4>Filters</h4>
        <div><input type="checkbox" checked={showHigh} onChange={() => setShowHigh(!showHigh)} /> High</div>
        <div><input type="checkbox" checked={showModerate} onChange={() => setShowModerate(!showModerate)} /> Moderate</div>
        <div><input type="checkbox" checked={showLow} onChange={() => setShowLow(!showLow)} /> Low</div>
        <div><input type="checkbox" checked={showUnverified} onChange={() => setShowUnverified(!showUnverified)} /> Unverified</div>
        <div><input type="checkbox" checked={showPositive} onChange={() => setShowPositive(!showPositive)} /> ASF-positive</div>
        <hr />
        <div><input type="checkbox" checked={showRings} onChange={() => setShowRings(!showRings)} /> Show DA/BAI Rings</div>
      </div>

      {/* Map */}
      <MapContainer center={[13.96, 121.33]} zoom={12} style={{ height: "600px", width: "100%" }}>
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Farm pins */}
        {riskData
          .filter(farm => farm.latitude !== null && farm.longitude !== null)
          .filter(farm => {
            if (farm.confirmed_asf_case === "Yes") return showPositive;
            if (farm.risk_level === "High") return showHigh;
            if (farm.risk_level === "Moderate") return showModerate;
            if (farm.risk_level === "Low") return showLow;
            if (farm.risk_level === "Unverified") return showUnverified;
            return true;
          })
          .map((farm) => (
            <CircleMarker
              key={farm.id}
              center={[farm.latitude!, farm.longitude!]}
              radius={farm.confirmed_asf_case === "Yes" ? 10 : 6}
              color={farm.confirmed_asf_case === "Yes" ? "purple" : (riskColors[farm.risk_level] || "blue")}
              fillOpacity={0.9}
            >
               <Popup>
    {/* ✅ Scrollable wrapper */}
    <div style={{ maxHeight: "250px", overflowY: "auto", fontSize: "13px" }}>
      <strong>Farm #{farm.id}</strong><br />
      <h5>Farmer details</h5>
      Date Uploaded: {farm.date_uploaded}<br />
      Farmer Name: {farm.farmername}<br />
      Type Of Farm: {farm.farm_type}<br />
      Total Farm Population: {farm.population}<br />
      Rsba Registered: {String(farm.rsba_registered)}<br />
      Rsba Control Number: {farm.rsba_control_number}<br />
      Biosecurity Level1 Compliant: {String(farm.biosecurity_level1)}<br />
      Farm Density: {farm.farm_density}<br />
      Nearest Farm Km: {farm.nearest_farm_km}<br />
      Province: {farm.province}<br />
      Access Road Nearby: {String(farm.access_road_nearby)}<br />
      Nearest Road Km: {farm.nearest_road_km}<br />
      <hr />
      <h5>Location</h5>
      Municipality: {farm.municipality}<br />
      Barangay: {farm.barangay}<br />
      Latitude: {farm.latitude}<br />
      Longitude: {farm.longitude}<br />
      <hr />
      <h5>Risk assessment</h5>
      Risk level: {farm.risk_level}<br />
      Risk score: {farm.risk_score ?? "-"} / 100<br />
      DA/BAI zone: {farm.zone ?? "-"}<br />
      Action: {farm.action ?? "-"}<br />
      Distance to nearest case: {farm.distance_to_case ?? "-"}<br />
      Municipal outbreak: {farm.municipal_outbreak ?? "-"}<br />
      <hr />
      <h5>Predictors</h5>
      Swine population: {farm.swine_population}<br />
      Farm density: {farm.farm_density}<br />
      Biosecurity Level 1: {String(farm.biosecurity_level1)}<br />
      Nearest access road: {farm.nearest_road_km} km ({String(farm.access_road_nearby)})<br />
      Road link to nearest case: {farm.road_link_case ?? "-"}<br />
      Cluster: {farm.cluster ?? "-"}
    </div>
  </Popup>
            </CircleMarker>
          ))}

        {/* DA/BAI rings */}
        {showRings &&
          riskData
            .filter(farm => farm.confirmed_asf_case === "Yes" && farm.latitude !== null && farm.longitude !== null)
            .map((farm) => (
              <React.Fragment key={`rings-${farm.id}`}>
                <Circle center={[farm.latitude!, farm.longitude!]} radius={1000} color="red" fillOpacity={0.2} />
                <Circle center={[farm.latitude!, farm.longitude!]} radius={7000} color="yellow" fillOpacity={0.1} />
                <Circle center={[farm.latitude!, farm.longitude!]} radius={10000} color="green" fillOpacity={0.1} />
               </React.Fragment>
            ))}
      </MapContainer>
    </div>
  );
};

export default RiskMap;
              