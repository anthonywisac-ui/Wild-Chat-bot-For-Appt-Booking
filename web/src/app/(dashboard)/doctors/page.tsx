"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Plus } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { DoctorFormModal } from "@/components/DoctorFormModal";
import { api, type Doctor, DEPARTMENT_LABELS } from "@/lib/api";

export default function DoctorsPage() {
  const { bot } = useDashboard();
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Doctor | "new" | null>(null);

  useEffect(() => {
    api.doctors(bot.id).then((rows) => {
      setDoctors(rows);
      setLoading(false);
    });
  }, [bot.id]);

  function handleSaved(d: Doctor) {
    setDoctors((prev) => (prev.some((x) => x.id === d.id) ? prev.map((x) => (x.id === d.id ? d : x)) : [...prev, d]));
  }

  function handleDeleted(id: number) {
    setDoctors((prev) => prev.filter((x) => x.id !== id));
  }

  const byDept = doctors.reduce<Record<string, Doctor[]>>((acc, d) => {
    (acc[d.department] ??= []).push(d);
    return acc;
  }, {});

  return (
    <>
      <PageHeader
        title="Doctors"
        subtitle={`${doctors.length} doctors across your clinic`}
        action={
          <button
            onClick={() => setEditing("new")}
            className="bg-primary hover:bg-primary-dark transition-colors text-white text-[13px] font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5"
          >
            <Plus size={15} /> Add doctor
          </button>
        }
      />

      {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
      {!loading && doctors.length === 0 && (
        <p className="text-sm text-ink-faint py-10 text-center">No doctors added yet.</p>
      )}

      {Object.entries(byDept).map(([dept, list], gi) => (
        <div key={dept} className="mb-5">
          <p className="text-[12px] font-bold text-ink-faint tracking-wide mb-2.5 uppercase">
            {DEPARTMENT_LABELS[dept] ?? dept}
          </p>
          <div className="grid grid-cols-3 gap-3">
            {list.map((d, i) => (
              <motion.button
                key={d.id}
                onClick={() => setEditing(d)}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: (gi * list.length + i) * 0.03 }}
                className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)] flex items-center gap-3 text-left hover:[box-shadow:var(--shadow-soft),0_0_0_2px_var(--color-primary)] transition-shadow"
              >
                <div className="w-10 h-10 rounded-full bg-primary-soft flex items-center justify-center text-[12px] font-bold text-primary-dark shrink-0">
                  {d.name
                    .split(" ")
                    .map((p) => p[0])
                    .slice(0, 2)
                    .join("")
                    .toUpperCase()}
                </div>
                <div>
                  <p className="text-[13.5px] font-semibold">{d.name}</p>
                  <p className="text-[11.5px] text-ink-muted capitalize">{d.gender}</p>
                  <p className="text-[11.5px] text-primary font-semibold mt-0.5">
                    ${d.consultation_fee} consultation
                  </p>
                </div>
              </motion.button>
            ))}
          </div>
        </div>
      ))}

      <DoctorFormModal
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
