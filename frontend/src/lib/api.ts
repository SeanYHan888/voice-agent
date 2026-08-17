const TOKEN_KEY = "maya.token";
const ROLE_KEY = "maya.role";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY);
}

export function setSession(token: string, role: string) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(ROLE_KEY, role);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (response.status === 401) {
    clearSession();
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }

  const text = await response.text();
  const body = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = body?.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string" ? detail : "Something went wrong",
    );
  }
  return body as T;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
};

// --- shapes returned by the services -----------------------------------------

export type Appointment = {
  id: number;
  patient_id: number;
  status: string;
  provider_name: string;
  visit_type: string;
  starts_at: string;
  requires_approval?: boolean;
};

export type Provider = {
  id: number;
  name: string;
  title: string;
};

export type Slot = {
  id: number;
  provider_id: number;
  provider_name: string;
  visit_type: string;
  starts_at: string;
};

export type Call = {
  id: number;
  transport: string;
  started_at: string;
  ended_at: string | null;
  patient_id: number | null;
  summary: string | null;
  intent: string | null;
  sentiment: string | null;
  has_feedback: boolean;
};

export type Patient = {
  id: number;
  first_name: string;
  last_name: string;
  dob: string;
  phone: string;
};

export type AdminTask = {
  id: number;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  call_id: number | null;
  created_at: string;
  resolved_at: string | null;
};

export type Stats = {
  calls_per_day: { day: string; calls: number }[];
  total_calls: number;
  booking_conversion: number;
  avg_feedback: number;
  feedback_count: number;
  appointments_booked: number;
  open_tasks: number;
  patients: number;
  intents: { intent: string; count: number }[];
  sentiments: { sentiment: string; count: number }[];
};

export type ChatTurn = {
  session_id: string;
  reply: string;
  tools_called: string[];
  guard: string | null;
  verified: boolean;
  patient_first_name: string | null;
};
