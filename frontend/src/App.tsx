import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { AuthProvider, RequireRole } from "@/lib/auth";
import { Landing } from "@/pages/Landing";
import { Login } from "@/pages/Login";
import { PatientHome } from "@/pages/PatientHome";
import { CallHistory } from "@/pages/CallHistory";
import { AdminDashboard } from "@/pages/AdminDashboard";
import { AdminQueue } from "@/pages/AdminQueue";
import { AdminAnalytics } from "@/pages/AdminAnalytics";
import { AdminInbox } from "@/pages/AdminInbox";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login mode="login" />} />
          <Route path="/register" element={<Login mode="register" />} />

          <Route
            element={
              <RequireRole role="patient">
                <Layout />
              </RequireRole>
            }
          >
            <Route path="/portal" element={<PatientHome />} />
            <Route path="/portal/calls" element={<CallHistory />} />
          </Route>

          <Route
            element={
              <RequireRole role="admin">
                <Layout />
              </RequireRole>
            }
          >
            <Route path="/admin" element={<AdminDashboard />} />
            <Route path="/admin/queue" element={<AdminQueue />} />
            <Route path="/admin/analytics" element={<AdminAnalytics />} />
            <Route path="/admin/inbox" element={<AdminInbox />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
