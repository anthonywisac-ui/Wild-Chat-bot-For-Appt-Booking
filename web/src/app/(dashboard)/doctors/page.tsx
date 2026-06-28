"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Doctor, DEPARTMENT_LABELS } from "@/lib/api";

export default function DoctorsPage() {
  const { bot } = useDashboard();
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.doctors(bot.id).then((rows) => {
      setDoctors(rows);
      setLoading(false);
    });
  }, [bot.id]);

  const byDept = doctors.reduce<Record<string, Doctor[]>>((acc, d) => {
    (acc[d.department] ??= []).push(d);
    return acc;
  }, {});

  return (
    <>
      <PageHeader title="Doctors" subtitle={`${doctors.length} doctors across your clinic`} />

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
              <motion.div
                key={d.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: (gi * list.length + i) * 0.03 }}
                className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)] flex items-center gap-3"
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
              </motion.div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
