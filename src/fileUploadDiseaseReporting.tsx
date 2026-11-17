import React, { useState } from "react";
import axios from "axios";

const DiseaseReportUpload: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);

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
      setResult(res.data);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={{ padding: "2rem" }}>
      <h2>Disease Reporting Upload</h2>
      <input type="file" accept=".csv" onChange={handleFileChange} />
      <button onClick={handleUpload} style={{ marginLeft: "1rem" }}>
        Upload
      </button>

      {result && (
        <div style={{ marginTop: "2rem" }}>
          <h3>Processed Report</h3>
          <p>Total Records: {result.total_records}</p>

          <table border={1} cellPadding={8} style={{ marginTop: "1rem", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Municipality</th>
                <th>Confirmed Cases</th>
              </tr>
            </thead>
            <tbody>
              {result.summary.map((row: any, index: number) => (
                <tr key={index}>
                  <td>{row.Municipality}</td>
                  <td>{row.ConfirmedCases}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default DiseaseReportUpload;
