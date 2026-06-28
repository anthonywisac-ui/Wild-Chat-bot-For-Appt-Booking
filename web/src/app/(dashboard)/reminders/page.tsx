"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, BellOff, Phone, Stethoscope, Wallet, ChevronDown } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Appointment, DEPARTMENT_LABELS } from "@/lib/api";

function relativeDue(dateStr: string): { label: string; tone: "ok" | "soon" | "overdue" } {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr);
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86400000);
  if (diffDays === 0) return { label: "Today", tone: "soon" };
  if (diffDays === 1) return { label: "Tomorrow", tone: "soon" };
  if (diffDays > 1) return { label: `In ${diffDays} days`, tone: "ok" };
  return { label: `${Math.abs(diffDays)} day${Math.abs(diffDays) > 1 ? "s" : ""} overdue`, tone: "overdue" };
}

const DUE_STYLE: Record<string, string> = {
  ok: "bg-bg text-ink-muted",
  soon: "bg-amber-soft text-amber",
  overdue: "bg-pink-soft text-pink",
};

export default function RemindersPage() {
  const { bot } = useDashboard();
  const [rows, setRows] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

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

        {rows.map((a, i) => {
          const due = relativeDue(a.appointment_date);
          const isOpen = expanded === a.id;
          return (
            <motion.div
              key={a.id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: Math.min(i, 12) * 0.03 }}
              className="border-b border-border last:border-0"
            >
              <button
                onClick={() => setExpanded(isOpen ? null : a.id)}
                className="w-full flex items-center gap-3 py-3 text-left"
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
                <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full shrink-0 ${DUE_STYLE[due.tone]}`}>
                  {due.label}
                </span>
                <ChevronDown
                  size={15}
                  className={`text-ink-faint shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
                />
              </button>

              <AnimatePresence>
                {isOpen && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="pb-3 pl-11 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-ink-muted">
                      <span className="flex items-center gap-1.5">
                        <Phone size={13} /> {a.customer_phone}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Stethoscope size={13} /> {a.doctor_name ?? "Unassigned"} · {DEPARTMENT_LABELS[a.department] ?? a.department}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Wallet size={13} /> ${a.consultation_fee}
                      </span>
                      <button
                        onClick={() => markReminded(a.id)}
                        className="text-[11.5px] font-semibold text-primary border border-primary/30 rounded-lg px-3 py-1.5 hover:bg-primary-soft transition-colors ml-auto"
                      >
                        Mark reminded
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>
    </>
  );
}
