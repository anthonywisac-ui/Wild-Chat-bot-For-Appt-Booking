"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Bell, BellOff } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Appointment } from "@/lib/api";

export default function RemindersPage() {
  const { bot } = useDashboard();
  const [rows, setRows] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.appointments(bot.id, { limit: 200 }).then((res) => {
      const due = res.appointments
        .filter((a) => !a.reminder_sent && a.status !== "Cancelled" && a.status !== "Completed")
        .sort((a, b) => a.appointment_date.localeCompare(b.appointment_date));
      setRows(due);
      setLoading(false);
    });
  }, [bot.id]);

  async function markReminded(id: number) {
    await api.updateAppointment(bot.id, id, { reminder_sent: true });
    setRows((prev) => prev.filter((r) => r.id !== id));
  }

  return (
    <>
      <PageHeader
        title="Reminders"
        subtitle={`${rows.length} upcoming appointments without a reminder sent yet`}
      />

      <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]">
        {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
        {!loading && rows.length === 0 && (
          <div className="py-10 text-center text-ink-faint">
            <BellOff size={22} className="mx-auto mb-2" />
            <p className="text-sm">All caught up — no reminders pending.</p>
          </div>
        )}

        {rows.map((a, i) => (
          <motion.div
            key={a.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: Math.min(i, 12) * 0.03 }}
            className="flex items-center gap-3 py-3 border-b border-border last:border-0"
          >
            <div className="w-8 h-8 rounded-[10px] bg-amber-soft flex items-center justify-center shrink-0">
              <Bell size={15} className="text-amber" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[13.5px] font-semibold truncate">{a.customer_name}</p>
              <p className="text-xs text-ink-muted truncate">
                {a.service} · {a.appointment_date} {a.appointment_time}
              </p>
            </div>
            <button
              onClick={() => markReminded(a.id)}
              className="text-[11.5px] font-semibold text-primary border border-primary/30 rounded-lg px-3 py-1.5 hover:bg-primary-soft transition-colors shrink-0"
            >
              Mark reminded
            </button>
          </motion.div>
        ))}
      </div>
    </>
  );
}
