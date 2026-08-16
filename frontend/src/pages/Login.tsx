import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Stethoscope } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/States";
import { useAuth } from "@/lib/auth";

export function Login({ mode }: { mode: "login" | "register" }) {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const role = mode === "login" ? await login(email, password) : await register(email, password);
      navigate(role === "admin" ? "/admin" : "/portal");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <Link to="/" className="mb-2 flex w-fit items-center gap-2 hover:opacity-80">
            <Stethoscope className="size-5 text-primary" />
            <span className="font-semibold">Assort Dermatology</span>
          </Link>
          <CardTitle>{mode === "login" ? "Sign in" : "Create an account"}</CardTitle>
          <CardDescription>
            {mode === "login"
              ? "Access your visits and talk to Maya."
              : "You'll link your clinic record after signing up."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <ErrorNote message={error} />}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              {mode === "login" ? (
                <>
                  New here?{" "}
                  <Link to="/register" className="text-primary hover:underline">
                    Create an account
                  </Link>
                </>
              ) : (
                <>
                  Already registered?{" "}
                  <Link to="/login" className="text-primary hover:underline">
                    Sign in
                  </Link>
                </>
              )}
            </p>
          </form>
        </CardContent>
      </Card>
      <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">
        ← Back to home
      </Link>
    </div>
  );
}
