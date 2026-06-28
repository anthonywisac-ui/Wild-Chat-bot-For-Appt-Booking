"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { FilterTabs } from "@/components/FilterTabs";
import { StatusPill } from "@/components/StatusPill";
import { api, type Appointment } from "@/lib/api";

const STATUS_OPTIONS = [
  { label: "All", value: "" },
  { label: "Scheduled", value: "Scheduled" },
  { label: "Confirmed", value: "Confirmed" },
  { label: "Completed", value: "Completed" },
  { label: "Cancelled", value: "Cancelled" },
];

export default function AppointmentsPage() {
  const { bot } = useDashboard();
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<Appointment[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .appointments(bot.id, status ? { status, limit: 100 } : { limit: 100 })
      .then((res) => {
        setRows(res.appointments);
        setTotal(res.total);
        setLoading(false);
      });
  }, [bot.id, status]);

  async function setApptStatus(id: number, newStatus: string) {
    await api.updateAppointmentStatus(bot.id, id, newStatus);
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, status: newStatus } : r)));
  }

  return (
    <>
      <PageHeader title="Appointments" subtitle={`${total} total bookings`} />
      <FilterTabs options={STATUS_OPTIONS} value={status} onChange={setStatus} />

      <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]">
        {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
        {!loading && rows.length === 0 && (
          <p className="text-sm text-ink-faint py-10 text-center">No appointments found.</p>
        )}

        {!loading && rows.length > 0 && (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] font-bold text-ink-faint tracking-wide">
                <th className="pb-2.5 pr-3">Patient</th>
                <th className="pb-2.5 pr-3">Treatment</th>
                <th className="pb-2.5 pr-3">Doctor</th>
                <th className="pb-2.5 pr-3">Date &amp; time</th>
                <th className="pb-2.5 pr-3">Fee</th>
                <th className="pb-2.5 pr-3">Status</th>
                <th className="pb-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a, i) => (
                <motion.tr
                  key={a.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i, 10) * 0.025 }}
                  className="border-t border-border"
                >
                  <td className="py-2.5 pr-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-full bg-primary-soft flex items-center justify-center text-[10.5px] font-bold text-primary-dark shrink-0">
                        {a.customer_name.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <p className="font-semibold">{a.customer_name}</p>
                        <p className="text-[11px] text-ink-faint">{a.customer_phone}</p>
                      </div>
                    </div>
                  </td>
                  <td className="py-2.5 pr-3 text-ink-muted">{a.service}</td>
                  <td className="py-2.5 pr-3 text-ink-muted">{a.doctor_name ?? "Unassigned"}</td>
                  <td className="py-2.5 pr-3 text-ink-muted">
                    {a.appointment_date} · {a.appointment_time}
                  </td>
                  <td className="py-2.5 pr-3 text-ink-muted">${a.consultation_fee}</td>
                  <td className="py-2.5 pr-3">
                    <StatusPill status={a.status} />
                  </td>
                  <td className="py-2.5">
                    <div className="flex gap-1.5">
                      {a.status !== "Confirmed" && a.status !== "Cancelled" && (
                        <button
                          onClick={() => setApptStatus(a.id, "Confirmed")}
                          className="text-[11px] font-semibold text-emerald border border-emerald/30 rounded-lg px-2 py-1 hover:bg-emerald-soft transition-colors"
                        >
                          Confirm
                        </button>
                      )}
                      {a.status !== "Cancelled" && a.status !== "Completed" && (
                        <button
                          onClick={() => setApptStatus(a.id, "Cancelled")}
                          className="text-[11px] font-semibold text-pink border border-pink/30 rounded-lg px-2 py-1 hover:bg-pink-soft transition-colors"
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
