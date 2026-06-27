// API client for the FastAPI backend. Mirrors the auth pattern the legacy
// cms/static/index.html already used: JWT in localStorage under the key
// "token", sent as a Bearer header on every request.

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? (typeof window !== "undefined" ? "" : "");

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore non-JSON error bodies
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: () =>
    request<{ username: string; role: string; user_id: number; bots: string[] }>(
      "/auth/me"
    ),
  stats: () => request<Stats>("/api/crm/stats"),
  bots: () => request<BotSummary[]>("/api/crm/bots/whatsapp"),
  appointments: (botId: number, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)])
    ).toString();
    return request<{ total: number; appointments: Appointment[] }>(
      `/api/crm/bots/${botId}/appointments${qs ? `?${qs}` : ""}`
    );
  },
  updateAppointmentStatus: (botId: number, appointmentId: number, status: string) =>
    request<{ status: string; id: number; new_status: string }>(
      `/api/crm/bots/${botId}/appointments/${appointmentId}`,
      { method: "PATCH", body: JSON.stringify({ status }) }
    ),
  leads: (botId: number) => request<Lead[]>(`/api/crm/bots/${botId}/leads`),
  doctors: (botId: number) => request<Doctor[]>(`/api/crm/bots/${botId}/doctors`),
};

export interface Stats {
  appointments_today: number;
  revenue_series: { date: string; revenue: number }[];
}

export interface BotSummary {
  id: number;
  name: string;
  bot_type: string;
  business_name: string;
  status: string;
  messenger_page_id?: string | null;
  instagram_account_id?: string | null;
  manychat_api_key?: string | null;
  waba_id?: string | null;
  wwebjs_session?: string | null;
}

export interface Appointment {
  id: number;
  customer_name: string;
  customer_phone: string;
  service: string;
  department: string;
  doctor_name: string | null;
  appointment_date: string;
  appointment_time: string;
  status: string;
  consultation_fee: number;
}

export interface Lead {
  id: number;
  phone: string;
  goal: string;
  concern: string;
  treatment_interest: string;
  budget_level: string;
  lead_quality: string;
  status: string;
  estimated_value: number;
  created_at: string;
}

export interface Doctor {
  id: number;
  department: string;
  name: string;
  gender: string;
  consultation_fee: number;
}
