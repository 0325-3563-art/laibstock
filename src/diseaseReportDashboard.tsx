import React, { useState } from "react";
import axios from "axios";

const DiseaseReportDashboard: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<any[]>([]);
  const [totalRecords, setTotalRecords] = useState<number>(0);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await axios.post("http://localhost:8000/upload-disease-report", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setSummary(res.data.summary);
      setTotalRecords(res.data.total_records);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={{ padding: "2rem", fontFamily: "Arial, sans-serif" }}>
      <h2>ASF Disease Reporting</h2>
      <input type="file" accept=".csv" onChange={handleFileChange} />
      <button onClick={handleUpload} style={{ marginLeft: "1rem" }}>
        Upload Report
      </button>

      {summary.length > 0 && (
        <div style={{ marginTop: "2rem" }}>
          <h3 style={{ textAlign: "center" }}>Summary</h3>
          <p style={{ textAlign: "center" }}>Total Records: {totalRecords}</p>

          {/* Center the table */}
          <div style={{ width: "100%", display: "block" }}>
            <table
              border={1}
              cellPadding={8}
              style={{
                margin: "0 auto",          // forces horizontal centering
                borderCollapse: "collapse",
                textAlign: "center",       // centers text inside cells
                minWidth: "400px",         // optional: keeps table wide enough
              }}
            >
              <thead>
                <tr>
                  <th>Municipality</th>
                  <th>Confirmed Cases</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((row, index) => (
                  <tr key={index}>
                    <td>{row.Municipality}</td>
                    <td>{row.ConfirmedCases}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default DiseaseReportDashboard;
