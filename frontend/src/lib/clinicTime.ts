/**
 * The mock clinic keeps its schedule on one clock — UTC — and Maya speaks slot times
 * on that clock ("Tuesday at 9:00 AM"). The portal renders appointment and slot times
 * the same way, so what a Patient reads here is exactly what they can say to Maya.
 */
const CLINIC_TZ = "UTC";

export function formatClinicTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: CLINIC_TZ,
  });
}

export function formatClinicDay(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: CLINIC_TZ,
  });
}

export function formatClinicWhen(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: CLINIC_TZ,
  });
}

/** YYYY-MM-DD of the instant on the clinic clock — the key the calendar buckets by. */
export function clinicDateKey(d: Date) {
  return d.toISOString().slice(0, 10);
}

/** Today on the clinic clock, at midnight UTC. */
export function clinicToday() {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

/** Monday (UTC midnight) of the week containing `d`. */
export function startOfClinicWeek(d: Date) {
  const day = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const offset = (day.getUTCDay() + 6) % 7; // Sun=0 → 6, Mon=1 → 0
  day.setUTCDate(day.getUTCDate() - offset);
  return day;
}

export function addDays(d: Date, n: number) {
  const out = new Date(d);
  out.setUTCDate(out.getUTCDate() + n);
  return out;
}
