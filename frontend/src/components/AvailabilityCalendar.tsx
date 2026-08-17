import { useEffect, useMemo, useState } from "react";
import { CalendarRange, ChevronLeft, ChevronRight, Stethoscope } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorNote, Loading } from "@/components/States";
import { api, type Provider, type Slot } from "@/lib/api";
import {
  addDays,
  clinicDateKey,
  clinicToday,
  formatClinicTime,
  startOfClinicWeek,
} from "@/lib/clinicTime";
import { cn } from "@/lib/utils";

const VISIT_TYPES = ["New Patient", "Follow-up"] as const;
type VisitFilter = "All" | (typeof VISIT_TYPES)[number];

const WEEKDAY = new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: "UTC" });
const MONTH_DAY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

/**
 * Who has open times this week, at a glance. Rows are Providers, columns are days,
 * cells count the open Slots. Picking a cell lists the times; picking a time hands
 * it to the caller so Maya can book it.
 */
export function AvailabilityCalendar({
  onPickSlot,
  refreshKey = 0,
}: {
  onPickSlot: (slot: Slot) => void;
  /** Bump to refetch — e.g. after Maya books, so the counts drop. */
  refreshKey?: number;
}) {
  const thisWeek = useMemo(() => {
    const today = clinicToday();
    // Weekends: the clinic is closed, so start on the coming Monday.
    return startOfClinicWeek(today.getUTCDay() === 0 || today.getUTCDay() === 6 ? addDays(today, 2) : today);
  }, []);
  const [weekStart, setWeekStart] = useState(thisWeek);
  const [filter, setFilter] = useState<VisitFilter>("All");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<{ providerId: number; day: string } | null>(null);

  useEffect(() => {
    api.get<Provider[]>("/domain/providers").then(setProviders).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .get<Slot[]>(`/domain/slots/calendar?start=${clinicDateKey(weekStart)}&days=7`)
      .then((rows) => {
        if (!cancelled) setSlots(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load availability");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [weekStart, refreshKey]);

  const visible = useMemo(
    () => (filter === "All" ? slots : slots.filter((s) => s.visit_type === filter)),
    [slots, filter],
  );

  // provider id → day key → open slots, sorted by time (the API already orders them).
  const byCell = useMemo(() => {
    const map = new Map<number, Map<string, Slot[]>>();
    for (const slot of visible) {
      const day = slot.starts_at.slice(0, 10);
      const row = map.get(slot.provider_id) ?? new Map<string, Slot[]>();
      row.set(day, [...(row.get(day) ?? []), slot]);
      map.set(slot.provider_id, row);
    }
    return map;
  }, [visible]);

  const days = useMemo(() => {
    const all = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
    // Mon–Fri always; a weekend day only when something is actually open on it.
    return all.filter((d, i) => i < 5 || visible.some((s) => s.starts_at.slice(0, 10) === clinicDateKey(d)));
  }, [weekStart, visible]);

  const todayKey = clinicDateKey(clinicToday());
  const pickedSlots = picked ? byCell.get(picked.providerId)?.get(picked.day) ?? [] : [];
  const pickedProvider = providers.find((p) => p.id === picked?.providerId);
  const weekTotal = visible.length;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarRange className="size-4" /> Who's available
            </CardTitle>
            <CardDescription>
              Open times per provider. Pick a day, then a time, and Maya will book it.
            </CardDescription>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Previous week"
              disabled={weekStart <= thisWeek}
              onClick={() => {
                setWeekStart((w) => addDays(w, -7));
                setPicked(null);
              }}
            >
              <ChevronLeft />
            </Button>
            <span className="min-w-[9.5rem] text-center text-sm font-medium tabular-nums">
              {MONTH_DAY.format(weekStart)} – {MONTH_DAY.format(addDays(weekStart, 4))}
            </span>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Next week"
              onClick={() => {
                setWeekStart((w) => addDays(w, 7));
                setPicked(null);
              }}
            >
              <ChevronRight />
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1 pt-1">
          {(["All", ...VISIT_TYPES] as VisitFilter[]).map((option) => (
            <Button
              key={option}
              size="xs"
              variant={filter === option ? "default" : "outline"}
              onClick={() => {
                setFilter(option);
                setPicked(null);
              }}
            >
              {option}
            </Button>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">
            {loading ? "" : `${weekTotal} open ${weekTotal === 1 ? "time" : "times"} this week`}
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {error && <ErrorNote message={error} />}
        {loading && slots.length === 0 ? (
          <Loading label="Checking the schedule…" />
        ) : providers.length === 0 ? (
          <Empty>No providers are listed.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-separate border-spacing-y-1 text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th className="pb-1 text-left font-medium">Provider</th>
                  {days.map((d) => {
                    const key = clinicDateKey(d);
                    return (
                      <th key={key} className="pb-1 text-center font-medium">
                        <div className={cn(key === todayKey && "text-primary")}>{WEEKDAY.format(d)}</div>
                        <div className="text-[11px] font-normal">{MONTH_DAY.format(d)}</div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {providers.map((provider) => {
                  const row = byCell.get(provider.id);
                  return (
                    <tr key={provider.id}>
                      <td className="pr-3 align-middle">
                        <div className="flex items-center gap-2">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary">
                            <Stethoscope className="size-4 text-secondary-foreground" />
                          </span>
                          <div className="leading-tight">
                            <div className="font-medium">{provider.name}</div>
                            <div className="text-xs text-muted-foreground">{provider.title}</div>
                          </div>
                        </div>
                      </td>
                      {days.map((d) => {
                        const key = clinicDateKey(d);
                        const open = row?.get(key)?.length ?? 0;
                        const isPicked = picked?.providerId === provider.id && picked.day === key;
                        return (
                          <td key={key} className="px-0.5 text-center align-middle">
                            <button
                              type="button"
                              disabled={open === 0}
                              aria-pressed={isPicked}
                              aria-label={`${provider.name}, ${WEEKDAY.format(d)} ${MONTH_DAY.format(d)}: ${open} open`}
                              onClick={() => setPicked(isPicked ? null : { providerId: provider.id, day: key })}
                              className={cn(
                                "h-11 w-full rounded-lg border text-sm tabular-nums transition-colors",
                                open === 0 && "border-dashed text-muted-foreground/60",
                                open > 0 && open < 6 && "border-transparent bg-accent/60 text-accent-foreground hover:bg-accent",
                                open >= 6 && "border-transparent bg-success/15 text-foreground hover:bg-success/25",
                                isPicked && "ring-2 ring-primary ring-offset-1",
                              )}
                            >
                              {open === 0 ? "—" : (
                                <>
                                  <span className="font-semibold">{open}</span>
                                  <span className="ml-1 text-[11px] font-normal opacity-80">open</span>
                                </>
                              )}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {picked && pickedProvider && (
          <div className="rounded-lg border bg-muted/40 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{pickedProvider.name}</span>
              <span className="text-muted-foreground">·</span>
              <span>{WEEKDAY.format(new Date(picked.day))} {MONTH_DAY.format(new Date(picked.day))}</span>
              <Badge variant="outline" className="ml-auto text-[10px] font-normal">
                clinic time
              </Badge>
            </div>
            {VISIT_TYPES.filter((vt) => pickedSlots.some((s) => s.visit_type === vt)).map((vt) => (
              <div key={vt} className="mb-2 last:mb-0">
                <div className="mb-1 text-xs text-muted-foreground">
                  {vt} · {vt === "New Patient" ? "30" : "15"} min
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {pickedSlots
                    .filter((s) => s.visit_type === vt)
                    .map((slot) => (
                      <Button
                        key={slot.id}
                        size="sm"
                        variant="outline"
                        className="tabular-nums"
                        onClick={() => onPickSlot(slot)}
                      >
                        {formatClinicTime(slot.starts_at)}
                      </Button>
                    ))}
                </div>
              </div>
            ))}
            <p className="mt-2 text-xs text-muted-foreground">
              Choose a time to write the request into Maya's box — send it and she'll book it.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
