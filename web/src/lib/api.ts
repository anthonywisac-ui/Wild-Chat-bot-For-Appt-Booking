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
  updateBot: (botId: number, fields: Record<string, string | number>) =>
    request<{ status: string; id: number; changes: string[] }>(
      `/api/crm/bots/whatsapp/${botId}`,
      { method: "PUT", body: JSON.stringify(fields) }
    ),
  appointments: (botId: number, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)])
    ).toString();
    return request<{ total: number; appointments: Appointment[] }>(
      `/api/crm/bots/${botId}/appointments${qs ? `?${qs}` : ""}`
    );
  },
  updateAppointment: (
    botId: number,
    appointmentId: number,
    body: { status?: string; reminder_sent?: boolean }
  ) =>
    request<{ status: string; id: number; new_status: string; reminder_sent: boolean }>(
      `/api/crm/bots/${botId}/appointments/${appointmentId}`,
      { method: "PATCH", body: JSON.stringify(body) }
    ),
  updateAppointmentStatus: (botId: number, appointmentId: number, status: string) =>
    api.updateAppointment(botId, appointmentId, { status }),
  leads: (botId: number) => request<Lead[]>(`/api/crm/bots/${botId}/leads`),
  doctors: (botId: number) => request<Doctor[]>(`/api/crm/bots/${botId}/doctors`),
  procedures: (botId: number) => request<Procedure[]>(`/api/crm/bots/${botId}/procedures`),
  patients: (botId: number) => request<Patient[]>(`/api/crm/bots/${botId}/patients`),
  seedDemoData: (botId: number) =>
    request<{ message: string }>(`/api/crm/bots/${botId}/seed-demo-data`, {
      method: "POST",
    }),
  team: (botId: number) =>
    request<{ user_id: number; username: string; role: "owner" | "member" }[]>(
      `/api/crm/bots/${botId}/team`
    ),
  addTeamMember: (botId: number, username: string, password: string) =>
    request<{ status: string; user_id: number; username: string }>(
      `/api/crm/bots/${botId}/team`,
      { method: "POST", body: JSON.stringify({ username, password }) }
    ),
  removeTeamMember: (botId: number, userId: number) =>
    request<{ status: string }>(`/api/crm/bots/${botId}/team/${userId}`, {
      method: "DELETE",
    }),
  createProcedure: (botId: number, body: ProcedurePayload) =>
    request<Procedure>(`/api/crm/bots/${botId}/procedures`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProcedure: (botId: number, procedureId: number, body: Partial<ProcedurePayload>) =>
    request<Procedure>(`/api/crm/bots/${botId}/procedures/${procedureId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteProcedure: (botId: number, procedureId: number) =>
    request<{ status: string }>(`/api/crm/bots/${botId}/procedures/${procedureId}`, {
      method: "DELETE",
    }),
  createDoctor: (botId: number, body: DoctorPayload) =>
    request<Doctor>(`/api/crm/bots/${botId}/doctors`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateDoctor: (botId: number, doctorId: number, body: Partial<DoctorPayload>) =>
    request<Doctor>(`/api/crm/bots/${botId}/doctors/${doctorId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteDoctor: (botId: number, doctorId: number) =>
    request<{ status: string }>(`/api/crm/bots/${botId}/doctors/${doctorId}`, {
      method: "DELETE",
    }),
  createAppointment: (botId: number, body: AppointmentCreatePayload) =>
    request<Appointment>(`/api/crm/bots/${botId}/appointments`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
  language?: string | null;
  ai_provider?: string | null;
  system_prompt?: string | null;
  provider?: string | null;
  meta_token?: string | null;
  phone_number_id?: string | null;
  waba_id?: string | null;
  wwebjs_session?: string | null;
  messenger_page_id?: string | null;
  messenger_token?: string | null;
  instagram_account_id?: string | null;
  instagram_token?: string | null;
  manychat_api_key?: string | null;
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
  reminder_sent?: boolean;
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
  bio?: string | null;
  consultation_fee: number;
}

export interface Procedure {
  id: number;
  department: string;
  name: string;
  sessions_required: number;
  fee_per_session: number;
  package_tier: string | null;
  description: string | null;
}

export interface Patient {
  id: number;
  phone: string;
  name: string;
  age: string | null;
  gender: string | null;
  city: string | null;
  created_at: string;
}

export interface ProcedurePayload {
  department: string;
  name: string;
  sessions_required: number;
  fee_per_session: number;
  package_tier?: string;
  description?: string;
}

export interface DoctorPayload {
  department: string;
  name: string;
  gender: string;
  bio?: string;
  consultation_fee: number;
}

export interface AppointmentCreatePayload {
  customer_name: string;
  customer_phone: string;
  department: string;
  appointment_date: string;
  appointment_time: string;
  procedure_id?: number;
  doctor_id?: number;
  consultation_fee: number;
  service?: string;
}

export const DEPARTMENT_LABELS: Record<string, string> = {
  skin: "Skin",
  hair: "Hair",
  laser: "Laser",
  body: "Body",
  dental: "Dental",
  injectables: "Injectables",
};
