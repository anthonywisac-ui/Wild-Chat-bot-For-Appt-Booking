"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, type Stats, type Appointment, type Lead } from "@/lib/api";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

const STATUS_COLORS: Record<string, string> = {
  Confirmed: "#15803D",
  Completed: "#4F46E5",
  Scheduled: "#B45309",
  Cancelled: "#BE185D",
};

const QUALITY_COLORS: Record<string, string> = {
  high: "#15803D",
  medium: "#B45309",
  low: "#BE185D",
};

export default function ReportsPage() {
  const { bot } = useDashboard();
  const [stats, setStats] = useState<Stats | null>(null);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);

  useEffect(() => {
    (async () => {
      const [s, a, l] = await Promise.all([
        api.stats(),
        api.appointments(bot.id, { limit: 200 }),
        api.leads(bot.id),
      ]);
      setStats(s);
      setAppointments(a.appointments);
      setLeads(l);
    })();
  }, [bot.id]);

  if (!stats) return <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>;

  const statusCounts: Record<string, number> = {};
  for (const a of appointments) statusCounts[a.status] = (statusCounts[a.status] ?? 0) + 1;
  const statusLabels = Object.keys(statusCounts);

  const qualityCounts: Record<string, number> = { high: 0, medium: 0, low: 0 };
  for (const l of leads) qualityCounts[l.lead_quality] = (qualityCounts[l.lead_quality] ?? 0) + 1;

  const revenueOptions: ApexOptions = {
    chart: { toolbar: { show: false } },
    stroke: { curve: "smooth", width: 3, colors: ["#4F46E5"] },
    fill: { type: "gradient", gradient: { opacityFrom: 0.3, opacityTo: 0 }, colors: ["#4F46E5"] },
    grid: { borderColor: "#ECECEC" },
    xaxis: { categories: stats.revenue_series.map((s) => s.date.slice(5)) },
    yaxis: { labels: { formatter: (v: number) => `$${v}` } },
    tooltip: { y: { formatter: (v: number) => `$${v.toLocaleString()}` } },
    dataLabels: { enabled: false },
  };

  const statusOptions: ApexOptions = {
    chart: { toolbar: { show: false } },
    labels: statusLabels,
    colors: statusLabels.map((s) => STATUS_COLORS[s] ?? "#9CA3AF"),
    legend: { position: "bottom", fontSize: "12px" },
    dataLabels: { enabled: false },
  };

  const qualityOptions: ApexOptions = {
    chart: { toolbar: { show: false } },
    plotOptions: { bar: { borderRadius: 6, columnWidth: "45%" } },
    colors: ["#4F46E5"],
    xaxis: { categories: ["High", "Medium", "Low"] },
    dataLabels: { enabled: false },
    grid: { borderColor: "#ECECEC" },
  };

  return (
    <>
      <PageHeader title="Reports" subtitle="Revenue, appointment, and lead trends" />

      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)] mb-3.5"
      >
        <p className="text-[13.5px] font-bold mb-3">Revenue, last 7 days</p>
        <Chart
          options={revenueOptions}
          series={[{ name: "Revenue", data: stats.revenue_series.map((s) => s.revenue) }]}
          type="area"
          height={220}
        />
      </motion.div>

      <div className="grid grid-cols-2 gap-3.5">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-[13.5px] font-bold mb-3">Appointments by status</p>
          {statusLabels.length === 0 ? (
            <p className="text-sm text-ink-faint py-10 text-center">No appointment data yet.</p>
          ) : (
            <Chart
              options={statusOptions}
              series={statusLabels.map((s) => statusCounts[s])}
              type="donut"
              height={240}
            />
          )}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-[13.5px] font-bold mb-3">Leads by quality</p>
          <Chart
            options={qualityOptions}
            series={[{ name: "Leads", data: [qualityCounts.high, qualityCounts.medium, qualityCounts.low] }]}
            type="bar"
            height={240}
          />
        </motion.div>
      </div>
    </>
  );
}
