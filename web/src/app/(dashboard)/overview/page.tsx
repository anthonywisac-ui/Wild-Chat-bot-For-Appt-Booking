"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Plus,
  CalendarDays,
  Users,
  Stethoscope,
  ArrowRight,
  MessageCircle,
} from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { RevenueChart } from "@/components/RevenueChart";
import { StatusPill } from "@/components/StatusPill";
import { NewAppointmentModal } from "@/components/NewAppointmentModal";
import { api, type Stats, type Appointment, type Lead, type Doctor } from "@/lib/api";

const QUALITY_SCORE: Record<string, number> = { low: 35, medium: 65, high: 90 };

export default function OverviewPage() {
  const { username, bot } = useDashboard();
  const [stats, setStats] = useState<Stats | null>(null);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [loading, setLoading] = useState(true);
  const [newApptOpen, setNewApptOpen] = useState(false);

  useEffect(() => {
    (async () => {
      const [s, a, l, d] = await Promise.all([
        api.stats(),
        api.appointments(bot.id, { limit: 5 }),
        api.leads(bot.id),
        api.doctors(bot.id),
      ]);
      setStats(s);
      setAppointments(a.appointments);
      setLeads(l);
      setDoctors(d);
      setLoading(false);
    })();
  }, [bot.id]);

  async function confirmAppointment(id: number) {
    await api.updateAppointmentStatus(bot.id, id, "Confirmed");
    setAppointments((prev) =>
      prev.map((a) => (a.id === id ? { ...a, status: "Confirmed" } : a))
    );
  }

  if (loading || !stats) {
    return <div className="text-sm text-ink-muted">Loading dashboard…</div>;
  }

  const newLeads = leads.filter((l) => l.status === "new").length;
  const avgQuality = leads.length
    ? Math.round(
        leads.reduce((sum, l) => sum + (QUALITY_SCORE[l.lead_quality] ?? 50), 0) / leads.length
      )
    : 0;
  const todaysRevenue = stats.revenue_series[stats.revenue_series.length - 1]?.revenue ?? 0;
  const channels = [
    { label: "WhatsApp", active: Boolean(bot.waba_id || bot.wwebjs_session), icon: MessageCircle },
    { label: "Messenger", active: Boolean(bot.messenger_page_id), icon: MessageCircle },
    { label: "Instagram", active: Boolean(bot.instagram_account_id), icon: MessageCircle },
  ];

  return (
    <>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[21px] font-extrabold tracking-tight">
            Good evening, {username}
          </h1>
          <p className="text-sm text-ink-muted mt-1">
            Here&apos;s an overview of your clinic and today&apos;s bookings.
          </p>
        </div>
        <button
          onClick={() => setNewApptOpen(true)}
          className="bg-primary hover:bg-primary-dark transition-colors text-white text-[13px] font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5"
        >
          <Plus size={15} />
          New appointment
        </button>
      </div>

      <NewAppointmentModal
        open={newApptOpen}
        onClose={() => setNewApptOpen(false)}
        botId={bot.id}
        onCreated={(a) => setAppointments((prev) => [a, ...prev].slice(0, 5))}
      />

      <div className="grid grid-cols-4 gap-3.5 mb-3.5">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="col-span-1 bg-primary rounded-2xl p-4 [box-shadow:var(--shadow-soft)] text-white"
        >
          <p className="text-xs text-white/70 mb-1">Revenue today</p>
          <p className="text-[26px] font-extrabold">${todaysRevenue.toLocaleString()}</p>
          <div className="mt-1 -mx-1">
            <RevenueChart series={stats.revenue_series} />
          </div>
        </motion.div>

        <StatCard
          delay={0.05}
          icon={CalendarDays}
          tint="bg-primary-soft text-primary-dark"
          label="Bookings today"
          value={stats.appointments_today}
        />
        <StatCard
          delay={0.1}
          icon={Users}
          tint="bg-pink-soft text-pink"
          label="New leads"
          value={newLeads}
        />
        <StatCard
          delay={0.15}
          icon={Stethoscope}
          tint="bg-emerald-soft text-emerald"
          label="Doctors available"
          value={doctors.length}
        />
      </div>

      <div className="grid grid-cols-[1.6fr_1fr] gap-3.5">
        <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]">
          <div className="flex items-baseline justify-between mb-3.5">
            <p className="text-[14.5px] font-bold">Upcoming appointments</p>
            <a
              href="/appointments"
              className="text-[12px] font-semibold text-primary flex items-center gap-1"
            >
              View all <ArrowRight size={12} />
            </a>
          </div>

          {appointments.length === 0 && (
            <p className="text-sm text-ink-faint py-6 text-center">
              No appointments yet.
            </p>
          )}

          {appointments.map((a, i) => (
            <motion.div
              key={a.id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.04 }}
              className="flex items-center gap-3 py-3 border-b border-border last:border-0"
            >
              <div className="w-9 h-9 rounded-full bg-primary-soft flex items-center justify-center text-[11px] font-bold text-primary-dark shrink-0">
                {a.customer_name.slice(0, 2).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13.5px] font-semibold truncate">{a.customer_name}</p>
                <p className="text-xs text-ink-muted truncate">
                  {a.service} · {a.doctor_name ?? "Unassigned"} · {a.appointment_date} {a.appointment_time}
                </p>
              </div>
              <StatusPill status={a.status} />
              {a.status === "Scheduled" && (
                <button
                  onClick={() => confirmAppointment(a.id)}
                  className="text-[11px] font-semibold text-primary border border-primary/30 rounded-lg px-2.5 py-1.5 hover:bg-primary-soft transition-colors"
                >
                  Confirm
                </button>
              )}
            </motion.div>
          ))}
        </div>

        <div className="flex flex-col gap-3.5">
          <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]">
            <p className="text-[13.5px] font-bold mb-3">Channels live</p>
            <div className="flex flex-col gap-2.5">
              {channels.map((c) => (
                <div key={c.label} className="flex items-center gap-2.5">
                  <c.icon size={15} className="text-ink-muted" />
                  <span className="text-[12.5px] flex-1">{c.label}</span>
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      c.active ? "bg-emerald" : "bg-ink-faint"
                    }`}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)] flex-1">
            <p className="text-[13.5px] font-bold mb-3">Lead quality</p>
            <p className="text-[21px] font-extrabold mb-2">
              {avgQuality}
              <span className="text-[13px] font-normal text-ink-muted"> / 100</span>
            </p>
            <div className="h-1.5 bg-bg rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full"
                style={{ width: `${avgQuality}%` }}
              />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function StatCard({
  icon: Icon,
  tint,
  label,
  value,
  delay = 0,
}: {
  icon: typeof CalendarDays;
  tint: string;
  label: string;
  value: number;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-card rounded-2xl p-4 [box-shadow:var(--shadow-soft)] flex flex-col justify-between"
    >
      <div className={`w-8 h-8 rounded-[10px] flex items-center justify-center ${tint}`}>
        <Icon size={16} />
      </div>
      <p className="text-[25px] font-extrabold mt-3">{value}</p>
      <p className="text-[11.5px] text-ink-muted">{label}</p>
    </motion.div>
  );
}
