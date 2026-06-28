"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Procedure, DEPARTMENT_LABELS } from "@/lib/api";

export default function TreatmentsPage() {
  const { bot } = useDashboard();
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.procedures(bot.id).then((rows) => {
      setProcedures(rows);
      setLoading(false);
    });
  }, [bot.id]);

  const byDept = procedures.reduce<Record<string, Procedure[]>>((acc, p) => {
    (acc[p.department] ??= []).push(p);
    return acc;
  }, {});

  return (
    <>
      <PageHeader title="Treatments" subtitle={`${procedures.length} treatments offered`} />

      {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
      {!loading && procedures.length === 0 && (
        <p className="text-sm text-ink-faint py-10 text-center">No treatments added yet.</p>
      )}

      {Object.entries(byDept).map(([dept, list], gi) => (
        <div key={dept} className="mb-5">
          <p className="text-[12px] font-bold text-ink-faint tracking-wide mb-2.5 uppercase">
            {DEPARTMENT_LABELS[dept] ?? dept}
          </p>
          <div className="bg-card rounded-2xl [box-shadow:var(--shadow-soft)] overflow-hidden">
            {list.map((p, i) => (
              <motion.div
                key={p.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: (gi * list.length + i) * 0.025 }}
                className="flex items-center justify-between px-4 py-3 border-b border-border last:border-0"
              >
                <div>
                  <p className="text-[13.5px] font-semibold">{p.name}</p>
                  <p className="text-[11.5px] text-ink-muted">
                    {p.sessions_required > 1
                      ? `${p.sessions_required} sessions`
                      : "Single session"}
                  </p>
                </div>
                <p className="text-[13.5px] font-bold text-primary">
                  ${p.fee_per_session}
                  {p.sessions_required > 1 && (
                    <span className="text-[11px] text-ink-faint font-normal"> /session</span>
                  )}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
