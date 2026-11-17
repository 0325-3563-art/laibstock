import { useState } from "react";
import axios from "axios";
import "./styles/MAOLogin.css";

type Props = {
  onLoginSuccess: () => void;
  onCancel?: () => void;
};

function MAOLogin({ onLoginSuccess, onCancel }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    try {
      setLoading(true);
      const res = await axios.post("http://localhost:8000/api/mao-login", {
        username,
        password,
      });
      if (res.data.success) {
        alert("Access granted!");
        onLoginSuccess(); // tell parent to show farmers
      } else {
        alert("Invalid credentials");
      }
    } catch (err) {
      alert("Login failed");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-card">
      <h2 className="login-title">MAO staff login</h2>

      <div className="login-fields">
        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
        />
      </div>

      <button
        type="button"
        className="login-primary"
        onClick={handleLogin}
        disabled={loading}
      >
        {loading ? "Logging in..." : "Login"}
      </button>

      {onCancel && (
        <button type="button" className="login-cancel" onClick={onCancel}>
          Cancel
        </button>
      )}
    </div>
  );
}

export default MAOLogin;