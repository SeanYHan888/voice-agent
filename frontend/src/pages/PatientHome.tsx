import { useCallback, useEffect, useState } from "react";
import { CalendarDays, Link2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Empty, ErrorNote, Loading } from "@/components/States";
import { MayaPanel } from "@/components/MayaPanel";
import { api, ApiError, type Appointment, type Patient } from "@/lib/api";

function formatWhen(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Until an account is linked to a clinic record, there is nothing to show. */
function ClaimRecord({ onLinked }: { onLinked: () => void }) {
  const [phone, setPhone] = useState("");
  const [dob, setDob] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/domain/patients/claim", { phone, dob });
      onLinked();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not link your record");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Link2 className="size-4" /> Link your clinic record
        </CardTitle>
        <CardDescription>
          Enter the phone number and date of birth we have on file. Demo record: Emma
          Patel, phone 555-010-0104, born 1996-01-09.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="phone">Phone on file</Label>
            <Input
              id="phone"
              placeholder="555-010-0104"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="dob">Date of birth</Label>
            <Input id="dob" type="date" value={dob} onChange={(e) => setDob(e.target.value)} required />
          </div>
          {error && <ErrorNote message={error} />}
          <Button type="submit" disabled={busy}>
            {busy ? "Checking…" : "Link record"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function PatientHome() {
  const [patient, setPatient] = useState<Patient | null>(null);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [needsLink, setNeedsLink] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const me = await api.get<Patient>("/domain/patients/me");
      setPatient(me);
      setNeedsLink(false);
      setAppointments(await api.get<Appointment[]>("/domain/appointments/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNeedsLink(true);
      else setError(e instanceof Error ? e.message : "Could not load your visits");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <Loading label="Loading your visits…" />;
  if (needsLink) return <ClaimRecord onLinked={load} />;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Hello{patient ? `, ${patient.first_name}` : ""}
          </h1>
          <p className="text-sm text-muted-foreground">
            Ask Maya to book, move, or cancel a visit — she handles it while you talk.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarDays className="size-4" /> Upcoming visits
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {error && <ErrorNote message={error} />}
            {appointments.length === 0 && !error ? (
              <Empty>Nothing booked yet. Ask Maya for the next available appointment.</Empty>
            ) : (
              appointments.map((appointment) => (
                <div
                  key={appointment.id}
                  className="flex items-center justify-between rounded-lg border px-4 py-3"
                >
                  <div>
                    <p className="font-medium">{formatWhen(appointment.starts_at)}</p>
                    <p className="text-sm text-muted-foreground">
                      {appointment.visit_type} · {appointment.provider_name}
                    </p>
                  </div>
                  <Badge variant={appointment.status === "booked" ? "secondary" : "outline"}>
                    {appointment.status === "pending_change" ? "staff reviewing" : appointment.status}
                  </Badge>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <MayaPanel onCallChanged={load} />
    </div>
  );
}
