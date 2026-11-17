import React, { createContext, useContext, useState } from "react";

export type Role = "farmer" | "staff" | null;

interface AuthValue {
  role: Role;
  username: string | null;
  loginFarmer: () => void;
  loginStaff: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);
const KEY = "laibstock_session";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
  const [role, setRole] = useState<Role>(saved?.role ?? null);
  const [username, setUsername] = useState<string | null>(saved?.username ?? null);

  const save = (r: Role, u: string | null) => {
    setRole(r);
    setUsername(u);
    sessionStorage.setItem(KEY, JSON.stringify({ role: r, username: u }));
  };

  const loginFarmer = () => save("farmer", null);

  // DEMO ONLY: replace with a call to your backend, e.g.
  // const res = await fetch("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
  // The server must return the role and a token/cookie.
  const loginStaff = async (u: string, p: string) => {
    if (u === "mao_staff" && p === "Mao@2026") {
      save("staff", u);
      return true;
    }
    return false;
  };

  const logout = () => {
    sessionStorage.removeItem(KEY);
    setRole(null);
    setUsername(null);
  };

  return (
    <AuthContext.Provider value={{ role, username, loginFarmer, loginStaff, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
};