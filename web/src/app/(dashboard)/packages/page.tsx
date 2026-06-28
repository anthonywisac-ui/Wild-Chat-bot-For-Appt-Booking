"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Layers, Plus } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { ProcedureFormModal } from "@/components/ProcedureFormModal";
import { api, type Procedure, DEPARTMENT_LABELS } from "@/lib/api";

export default function PackagesPage() {
  const { bot } = useDashboard();
  const [packages, setPackages] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Procedure | "new" | null>(null);

  useEffect(() => {
    api.procedures(bot.id).then((rows) => {
      setPackages(rows.filter((p) => p.sessions_required > 1));
      setLoading(false);
    });
  }, [bot.id]);

  function handleSaved(p: Procedure) {
    setPackages((prev) => {
      const exists = prev.some((x) => x.id === p.id);
      const next = exists ? prev.map((x) => (x.id === p.id ? p : x)) : [...prev, p];
      return next.filter((x) => x.sessions_required > 1);
    });
  }

  function handleDeleted(id: number) {
    setPackages((prev) => prev.filter((x) => x.id !== id));
  }

  return (
    <>
      <PageHeader
        title="Packages"
        subtitle={`${packages.length} multi-session packages`}
        action={
          <button
            onClick={() => setEditing("new")}
            className="bg-primary hover:bg-primary-dark transition-colors text-white text-[13px] font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5"
          >
            <Plus size={15} /> Add package
          </button>
        }
      />

      {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
      {!loading && packages.length === 0 && (
        <p className="text-sm text-ink-faint py-10 text-center">No packages set up yet.</p>
      )}

      <div className="grid grid-cols-3 gap-3.5">
        {packages.map((p, i) => (
          <motion.button
            key={p.id}
            onClick={() => setEditing(p)}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(i, 12) * 0.04 }}
            className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)] text-left hover:[box-shadow:var(--shadow-soft),0_0_0_2px_var(--color-primary)] transition-shadow"
          >
            <div className="w-9 h-9 rounded-[10px] bg-primary-soft flex items-center justify-center mb-3">
              <Layers size={16} className="text-primary-dark" />
            </div>
            <p className="text-[13.5px] font-semibold mb-0.5">{p.name}</p>
            <p className="text-[11.5px] text-ink-faint mb-3 uppercase tracking-wide">
              {DEPARTMENT_LABELS[p.department] ?? p.department}
            </p>
            <div className="flex items-baseline justify-between">
              <span className="text-[11.5px] text-ink-muted">
                {p.sessions_required} × ${p.fee_per_session}
              </span>
              <span className="text-[16px] font-extrabold text-primary">
                ${(p.sessions_required * p.fee_per_session).toLocaleString()}
              </span>
            </div>
          </motion.button>
        ))}
      </div>

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
