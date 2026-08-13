import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CalendarCheck, Inbox, Phone, Star } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorNote, Loading } from "@/components/States";
import { api, type Stats } from "@/lib/api";

const SENTIMENT_COLOURS: Record<string, string> = {
  positive: "hsl(142 71% 45%)",
  neutral: "hsl(215 16% 47%)",
  negative: "hsl(0 72% 51%)",
};

function Metric({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Phone;
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Icon className="size-4" />
          {label}
        </div>
        <p className="mt-2 text-3xl font-semibold tracking-tight">{value}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

export function AdminDashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Stats>("/domain/admin/stats")
      .then(setStats)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load stats"));
  }, []);

  if (error) return <ErrorNote message={error} />;
  if (!stats) return <Loading label="Loading clinic metrics…" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Clinic dashboard</h1>
        <p className="text-sm text-muted-foreground">
          What Maya handled, and what still needs a person.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric icon={Phone} label="Calls handled" value={stats.total_calls} />
        <Metric
          icon={CalendarCheck}
          label="Booking conversion"
          value={`${Math.round(stats.booking_conversion * 100)}%`}
          hint={`${stats.appointments_booked} appointments booked`}
        />
        <Metric
          icon={Star}
          label="Patient rating"
          value={stats.avg_feedback || "—"}
          hint={`${stats.feedback_count} ratings`}
        />
        <Metric icon={Inbox} label="Awaiting staff" value={stats.open_tasks} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Calls per day</CardTitle>
          </CardHeader>
          <CardContent className="h-64">
            {stats.calls_per_day.length === 0 ? (
              <Empty>No calls recorded yet.</Empty>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stats.calls_per_day}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(214 32% 91%)" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} />
                  <Tooltip cursor={{ fill: "hsl(210 40% 96%)" }} />
                  <Bar dataKey="calls" fill="hsl(199 89% 38%)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Why people called</CardTitle>
          </CardHeader>
          <CardContent className="h-64">
            {stats.intents.length === 0 ? (
              <Empty>No summarised calls yet.</Empty>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stats.intents} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(214 32% 91%)" />
                  <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis
                    type="category"
                    dataKey="intent"
                    width={110}
                    tickLine={false}
                    axisLine={false}
                    fontSize={12}
                  />
                  <Tooltip cursor={{ fill: "hsl(210 40% 96%)" }} />
                  <Bar dataKey="count" fill="hsl(199 89% 48%)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {stats.sentiments.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Caller sentiment</CardTitle>
          </CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={stats.sentiments} dataKey="count" nameKey="sentiment" label outerRadius={80}>
                  {stats.sentiments.map((entry) => (
                    <Cell
                      key={entry.sentiment}
                      fill={SENTIMENT_COLOURS[entry.sentiment] ?? "hsl(215 16% 47%)"}
                    />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
