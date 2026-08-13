import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, clearSession, getRole, getToken, setSession } from "./api";

type AuthState = {
  role: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<string>;
  register: (email: string, password: string) => Promise<string>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<string | null>(getRole());

  const value = useMemo<AuthState>(
    () => ({
      role,
      isAuthenticated: Boolean(getToken()),
      async login(email, password) {
        const result = await api.post<{ access_token: string; role: string }>("/auth/login", {
          email,
          password,
        });
        setSession(result.access_token, result.role);
        setRole(result.role);
        return result.role;
      },
      async register(email, password) {
        const result = await api.post<{ access_token: string; role: string }>("/auth/register", {
          email,
          password,
        });
        setSession(result.access_token, result.role);
        setRole(result.role);
        return result.role;
      },
      logout() {
        clearSession();
        setRole(null);
      },
    }),
    [role],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/** Route guard. The backend enforces this too — this only saves a wasted round trip. */
export function RequireRole({ role, children }: { role: string; children: ReactNode }) {
  const location = useLocation();
  const token = getToken();
  const currentRole = getRole();

  if (!token) return <Navigate to="/login" state={{ from: location }} replace />;
  if (currentRole !== role) {
    return <Navigate to={currentRole === "admin" ? "/admin" : "/portal"} replace />;
  }
  return <>{children}</>;
}
