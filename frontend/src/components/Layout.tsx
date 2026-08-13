import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Stethoscope, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const PATIENT_NAV = [
  { to: "/portal", label: "My visits", end: true },
  { to: "/portal/calls", label: "Call history" },
];

const ADMIN_NAV = [
  { to: "/admin", label: "Dashboard", end: true },
  { to: "/admin/queue", label: "Staff queue" },
  { to: "/admin/analytics", label: "Ask the data" },
  { to: "/admin/inbox", label: "SMS inbox" },
];

export function Layout() {
  const { role, logout } = useAuth();
  const navigate = useNavigate();
  const nav = role === "admin" ? ADMIN_NAV : PATIENT_NAV;

  return (
    <div className="min-h-screen">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <Link to={role === "admin" ? "/admin" : "/portal"} className="flex items-center gap-2">
            <Stethoscope className="size-5 text-primary" />
            <span className="font-semibold tracking-tight">Assort Dermatology</span>
          </Link>

          <nav className="flex items-center gap-1 text-sm">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:text-foreground",
                    isActive && "bg-accent text-accent-foreground font-medium",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">{role}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                logout();
                navigate("/login");
              }}
            >
              <LogOut className="size-4" />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
