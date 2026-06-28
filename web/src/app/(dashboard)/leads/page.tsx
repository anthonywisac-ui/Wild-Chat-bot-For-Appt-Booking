"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Lead } from "@/lib/api";

const QUALITY_STYLE: Record<string, string> = {
  high: "bg-emerald-soft text-emerald",
  medium: "bg-amber-soft text-amber",
  low: "bg-pink-soft text-pink",
};

const STATUS_STYLE: Record<string, string> = {
  new: "bg-primary-soft text-primary-dark",
  qualified: "bg-emerald-soft text-emerald",
  booked: "bg-emerald-soft text-emerald",
  lost: "bg-pink-soft text-pink",
};

export default function LeadsPage() {
  const { bot } = useDashboard();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.leads(bot.id).then((rows) => {
      setLeads(rows);
      setLoading(false);
    });
  }, [bot.id]);

  const totalValue = leads.reduce((sum, l) => sum + (l.estimated_value || 0), 0);

  return (
    <>
      <PageHeader
        title="Leads"
        subtitle={`${leads.length} leads · $${totalValue.toLocaleString()} estimated pipeline value`}
      />

      <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]">
        {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
        {!loading && leads.length === 0 && (
          <p className="text-sm text-ink-faint py-10 text-center">No leads yet.</p>
        )}

        {!loading && leads.length > 0 && (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] font-bold text-ink-faint tracking-wide">
                <th className="pb-2.5 pr-3">Phone</th>
                <th className="pb-2.5 pr-3">Interested in</th>
                <th className="pb-2.5 pr-3">Budget</th>
                <th className="pb-2.5 pr-3">Quality</th>
                <th className="pb-2.5 pr-3">Status</th>
                <th className="pb-2.5">Est. value</th>
              </tr>
            </thead>
            <tbody>
              {leads.map((l, i) => (
                <motion.tr
                  key={l.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i, 10) * 0.025 }}
                  className="border-t border-border"
                >
                  <td className="py-2.5 pr-3 font-semibold">{l.phone}</td>
                  <td className="py-2.5 pr-3 text-ink-muted">{l.treatment_interest || l.concern}</td>
                  <td className="py-2.5 pr-3 text-ink-muted capitalize">{l.budget_level}</td>
                  <td className="py-2.5 pr-3">
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-1 rounded-full capitalize ${
                        QUALITY_STYLE[l.lead_quality] ?? "bg-bg text-ink-muted"
                      }`}
                    >
                      {l.lead_quality}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3">
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-1 rounded-full capitalize ${
                        STATUS_STYLE[l.status] ?? "bg-bg text-ink-muted"
                      }`}
                    >
                      {l.status}
                    </span>
                  </td>
                  <td className="py-2.5 font-semibold">${l.estimated_value?.toLocaleString()}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
