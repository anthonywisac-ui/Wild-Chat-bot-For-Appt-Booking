"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Plus } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { ProcedureFormModal } from "@/components/ProcedureFormModal";
import { api, type Procedure, DEPARTMENT_LABELS } from "@/lib/api";

export default function TreatmentsPage() {
  const { bot } = useDashboard();
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Procedure | "new" | null>(null);

  useEffect(() => {
    api.procedures(bot.id).then((rows) => {
      setProcedures(rows);
      setLoading(false);
    });
  }, [bot.id]);

  function handleSaved(p: Procedure) {
    setProcedures((prev) => (prev.some((x) => x.id === p.id) ? prev.map((x) => (x.id === p.id ? p : x)) : [...prev, p]));
  }

  function handleDeleted(id: number) {
    setProcedures((prev) => prev.filter((x) => x.id !== id));
  }

  const byDept = procedures.reduce<Record<string, Procedure[]>>((acc, p) => {
    (acc[p.department] ??= []).push(p);
    return acc;
  }, {});

  return (
    <>
      <PageHeader
        title="Treatments"
        subtitle={`${procedures.length} treatments offered`}
        action={
          <button
            onClick={() => setEditing("new")}
            className="bg-primary hover:bg-primary-dark transition-colors text-white text-[13px] font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5"
          >
            <Plus size={15} /> Add treatment
          </button>
        }
      />

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
              <motion.button
                key={p.id}
                onClick={() => setEditing(p)}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: (gi * list.length + i) * 0.025 }}
                className="w-full flex items-center justify-between px-4 py-3 border-b border-border last:border-0 text-left hover:bg-bg transition-colors"
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
              </motion.button>
            ))}
          </div>
        </div>
      ))}

      <ProcedureFormModal
        open={editing !== null}
        onClose={() => setEditing(null)}
        botId={bot.id}
        initial={editing && editing !== "new" ? editing : undefined}
        onSaved={handleSaved}
        onDeleted={handleDeleted}
      />
    </>
  );
}
