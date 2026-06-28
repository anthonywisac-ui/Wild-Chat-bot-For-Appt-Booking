"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Patient } from "@/lib/api";

export default function PatientsPage() {
  const { bot } = useDashboard();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.patients(bot.id).then((rows) => {
      setPatients(rows);
      setLoading(false);
    });
  }, [bot.id]);

  return (
    <>
      <PageHeader title="Patients" subtitle={`${patients.length} patient records`} />

      <div className="grid grid-cols-3 gap-3">
        {loading && <p className="text-sm text-ink-muted py-6 text-center col-span-3">Loading…</p>}
        {!loading && patients.length === 0 && (
          <p className="text-sm text-ink-faint py-10 text-center col-span-3">
            No patient records yet.
          </p>
        )}

        {patients.map((p, i) => (
          <motion.div
            key={p.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(i, 12) * 0.03 }}
            className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)]"
          >
            <div className="flex items-center gap-3 mb-2.5">
              <div className="w-10 h-10 rounded-full bg-primary-soft flex items-center justify-center text-[12px] font-bold text-primary-dark shrink-0">
                {p.name
                  .split(" ")
                  .map((part) => part[0])
                  .slice(0, 2)
                  .join("")
                  .toUpperCase()}
              </div>
              <div>
                <p className="text-[13.5px] font-semibold">{p.name}</p>
                <p className="text-[11.5px] text-ink-faint">{p.phone}</p>
              </div>
            </div>
            <div className="flex gap-3 text-[11.5px] text-ink-muted">
              {p.age && <span>{p.age} yrs</span>}
              {p.gender && <span className="capitalize">{p.gender}</span>}
              {p.city && <span>{p.city}</span>}
            </div>
          </motion.div>
        ))}
      </div>
    </>
  );
}
