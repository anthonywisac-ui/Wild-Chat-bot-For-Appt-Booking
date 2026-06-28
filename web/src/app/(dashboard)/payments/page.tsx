"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Appointment } from "@/lib/api";

const PAID_STATUSES = new Set(["Confirmed", "Completed"]);

export default function PaymentsPage() {
  const { bot } = useDashboard();
  const [rows, setRows] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.appointments(bot.id, { limit: 200 }).then((res) => {
      setRows(res.appointments.filter((a) => PAID_STATUSES.has(a.status)));
      setLoading(false);
    });
  }, [bot.id]);

  const collected = rows
    .filter((a) => a.status === "Completed")
    .reduce((sum, a) => sum + a.consultation_fee, 0);
  const pending = rows
    .filter((a) => a.status === "Confirmed")
    .reduce((sum, a) => sum + a.consultation_fee, 0);

  return (
    <>
      <PageHeader
        title="Payments"
        subtitle="Derived from confirmed and completed appointment fees"
      />

      <div className="grid grid-cols-3 gap-3.5 mb-5">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-primary rounded-2xl p-4 [box-shadow:var(--shadow-soft)] text-white"
        >
          <p className="text-xs text-white/70 mb-1">Total collected</p>
          <p className="text-[24px] font-extrabold">${collected.toLocaleString()}</p>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-xs text-ink-muted mb-1">Pending (confirmed, not yet seen)</p>
          <p className="text-[24px] font-extrabold text-amber">${pending.toLocaleString()}</p>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-xs text-ink-muted mb-1">Total billed appointments</p>
          <p className="text-[24px] font-extrabold">{rows.length}</p>
        </motion.div>
      </div>

      <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]">
        {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
        {!loading && rows.length === 0 && (
          <p className="text-sm text-ink-faint py-10 text-center">No billable appointments yet.</p>
        )}

        {!loading && rows.length > 0 && (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] font-bold text-ink-faint tracking-wide">
                <th className="pb-2.5 pr-3">Patient</th>
                <th className="pb-2.5 pr-3">Treatment</th>
                <th className="pb-2.5 pr-3">Date</th>
                <th className="pb-2.5 pr-3">Status</th>
                <th className="pb-2.5">Amount</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a, i) => (
                <motion.tr
                  key={a.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i, 10) * 0.02 }}
                  className="border-t border-border"
                >
                  <td className="py-2.5 pr-3 font-semibold">{a.customer_name}</td>
                  <td className="py-2.5 pr-3 text-ink-muted">{a.service}</td>
                  <td className="py-2.5 pr-3 text-ink-muted">{a.appointment_date}</td>
                  <td className="py-2.5 pr-3">
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-1 rounded-full ${
                        a.status === "Completed"
                          ? "bg-emerald-soft text-emerald"
                          : "bg-amber-soft text-amber"
                      }`}
                    >
                      {a.status === "Completed" ? "Collected" : "Pending"}
                    </span>
                  </td>
                  <td className="py-2.5 font-bold">${a.consultation_fee}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
