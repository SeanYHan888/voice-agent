import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, Check, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorNote, Loading } from "@/components/States";
import { api, type AdminTask } from "@/lib/api";

/**
 * Where Maya stops and a person takes over: changes inside the 24-hour window, and calls
 * she escalated. Approving here is what actually executes the held change.
 */
export function AdminQueue() {
  const [tasks, setTasks] = useState<AdminTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setTasks(await api.get<AdminTask[]>("/domain/admin/tasks?status=open"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the queue");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function resolve(task: AdminTask, action: "approve" | "reject") {
    setPending(task.id);
    try {
      await api.post(`/domain/admin/tasks/${task.id}/${action}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the task");
    } finally {
      setPending(null);
    }
  }

  if (loading) return <Loading label="Loading the staff queue…" />;

  const approvals = tasks.filter((t) => t.kind === "approval");
  const escalations = tasks.filter((t) => t.kind === "escalation");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Staff queue</h1>
        <p className="text-sm text-muted-foreground">
          Maya holds these rather than acting alone. Nothing here has happened yet.
        </p>
      </div>

      {error && <ErrorNote message={error} />}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarClock className="size-4" /> Changes needing approval
          </CardTitle>
          <CardDescription>
            Cancellations and reschedules inside 24 hours of the visit.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {approvals.length === 0 ? (
            <Empty>Nothing waiting.</Empty>
          ) : (
            approvals.map((task) => (
              <div
                key={task.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3"
              >
                <div>
                  <p className="font-medium capitalize">
                    {String(task.payload.action)} · appointment #{String(task.payload.appointment_id)}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Requested {new Date(task.created_at).toLocaleString()}
                    {task.call_id ? ` · call #${task.call_id}` : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" disabled={pending === task.id} onClick={() => resolve(task, "approve")}>
                    <Check className="size-4" /> Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={pending === task.id}
                    onClick={() => resolve(task, "reject")}
                  >
                    <X className="size-4" /> Reject
                  </Button>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="size-4" /> Escalations
          </CardTitle>
          <CardDescription>
            Medical questions, complaints, and anything Maya declined to handle.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {escalations.length === 0 ? (
            <Empty>Nothing waiting.</Empty>
          ) : (
            escalations.map((task) => (
              <div key={task.id} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border px-4 py-3">
                <div className="max-w-xl">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{String(task.payload.reason).replace("_", " ")}</Badge>
                    <span className="text-sm text-muted-foreground">
                      {new Date(task.created_at).toLocaleString()}
                    </span>
                  </div>
                  {task.payload.detail ? (
                    <p className="mt-2 text-sm">“{String(task.payload.detail)}”</p>
                  ) : null}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending === task.id}
                  onClick={() => resolve(task, "approve")}
                >
                  <Check className="size-4" /> Mark handled
                </Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
