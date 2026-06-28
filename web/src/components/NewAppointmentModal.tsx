"use client";

import { useEffect, useState } from "react";
import { Modal } from "./Modal";
import {
  api,
  type Appointment,
  type Doctor,
  type Procedure,
  DEPARTMENT_LABELS,
} from "@/lib/api";

export function NewAppointmentModal({
  open,
  onClose,
  botId,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  botId: number;
  onCreated: (a: Appointment) => void;
}) {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [department, setDepartment] = useState("skin");
  const [procedureId, setProcedureId] = useState<number | "">("");
  const [doctorId, setDoctorId] = useState<number | "">("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [time, setTime] = useState("10:00");
  const [fee, setFee] = useState(0);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    Promise.all([api.doctors(botId), api.procedures(botId)]).then(([d, p]) => {
      setDoctors(d);
      setProcedures(p);
    });
  }, [open, botId]);

  useEffect(() => {
    if (!open) {
      setCustomerName("");
      setCustomerPhone("");
      setProcedureId("");
      setDoctorId("");
      setFee(0);
    }
  }, [open]);

  const deptProcedures = procedures.filter((p) => p.department === department);
  const deptDoctors = doctors.filter((d) => d.department === department);

  function handleProcedureChange(id: string) {
    const procId = id ? Number(id) : "";
    setProcedureId(procId);
    const proc = procedures.find((p) => p.id === procId);
    if (proc) setFee(proc.fee_per_session);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const proc = procedures.find((p) => p.id === procedureId);
      const appt = await api.createAppointment(botId, {
        customer_name: customerName,
        customer_phone: customerPhone,
        department,
        procedure_id: procedureId || undefined,
        doctor_id: doctorId || undefined,
        appointment_date: date,
        appointment_time: time,
        consultation_fee: fee,
        service: proc?.name,
      });
      onCreated(appt);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="New appointment" width={460}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-2.5">
        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Patient name</label>
            <input
              required
              value={customerName}
              onChange={(e) => setCustomerName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Phone</label>
            <input
              required
              value={customerPhone}
              onChange={(e) => setCustomerPhone(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-ink-muted mb-1">Department</label>
          <select
            value={department}
            onChange={(e) => {
              setDepartment(e.target.value);
              setProcedureId("");
              setDoctorId("");
            }}
            className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
          >
            {Object.entries(DEPARTMENT_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Treatment</label>
            <select
              value={procedureId}
              onChange={(e) => handleProcedureChange(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            >
              <option value="">Select…</option>
              {deptProcedures.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Doctor</label>
            <select
              value={doctorId}
              onChange={(e) => setDoctorId(e.target.value ? Number(e.target.value) : "")}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            >
              <option value="">Unassigned</option>
              {deptDoctors.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2.5">
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Date</label>
            <input
              type="date"
              required
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Time</label>
            <input
              type="time"
              required
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Fee ($)</label>
            <input
              type="number"
              min={0}
              value={fee}
              onChange={(e) => setFee(Number(e.target.value))}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="bg-primary hover:bg-primary-dark transition-colors text-white text-[13px] font-semibold py-2.5 rounded-xl disabled:opacity-60 mt-1.5"
        >
          {saving ? "Booking…" : "Book appointment"}
        </button>
      </form>
    </Modal>
  );
}
