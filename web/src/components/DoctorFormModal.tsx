"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { Modal } from "./Modal";
import { api, type Doctor, type DoctorPayload, DEPARTMENT_LABELS } from "@/lib/api";

export function DoctorFormModal({
  open,
  onClose,
  botId,
  initial,
  onSaved,
  onDeleted,
}: {
  open: boolean;
  onClose: () => void;
  botId: number;
  initial?: Doctor;
  onSaved: (d: Doctor) => void;
  onDeleted?: (id: number) => void;
}) {
  const [form, setForm] = useState<DoctorPayload>(
    initial
      ? {
          department: initial.department,
          name: initial.name,
          gender: initial.gender,
          bio: initial.bio ?? "",
          consultation_fee: initial.consultation_fee,
        }
      : { department: "skin", name: "", gender: "female", bio: "", consultation_fee: 0 }
  );
  const [saving, setSaving] = useState(false);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const result = initial
        ? await api.updateDoctor(botId, initial.id, form)
        : await api.createDoctor(botId, form);
      onSaved(result);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!initial) return;
    await api.deleteDoctor(botId, initial.id);
    onDeleted?.(initial.id);
    onClose();
  }

  return (
    <Modal open={open} onClose={onClose} title={initial ? "Edit doctor" : "Add doctor"}>
      <form onSubmit={handleSave} className="flex flex-col gap-2.5">
        <div>
          <label className="block text-[11px] font-semibold text-ink-muted mb-1">Name</label>
          <input
            required
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
          />
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Department</label>
            <select
              value={form.department}
              onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            >
              {Object.entries(DEPARTMENT_LABELS).map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Gender</label>
            <select
              value={form.gender}
              onChange={(e) => setForm((f) => ({ ...f, gender: e.target.value }))}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            >
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
          </div>
        </div>
        <div>
          <label className="block text-[11px] font-semibold text-ink-muted mb-1">Consultation fee ($)</label>
          <input
            type="number"
            min={0}
            required
            value={form.consultation_fee}
            onChange={(e) => setForm((f) => ({ ...f, consultation_fee: Number(e.target.value) }))}
            className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
          />
        </div>
        <div>
          <label className="block text-[11px] font-semibold text-ink-muted mb-1">Bio (optional)</label>
          <textarea
            rows={2}
            value={form.bio}
            onChange={(e) => setForm((f) => ({ ...f, bio: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary resize-none"
          />
        </div>

        <div className="flex items-center justify-between mt-1.5">
          {initial ? (
            <button
              type="button"
              onClick={handleDelete}
              className="text-pink hover:bg-pink-soft transition-colors p-1.5 rounded-lg"
              aria-label="Delete doctor"
            >
              <Trash2 size={15} />
            </button>
          ) : <span />}
          <button
            type="submit"
            disabled={saving}
            className="bg-primary hover:bg-primary-dark transition-colors text-white text-[12.5px] font-semibold px-4 py-2 rounded-lg disabled:opacity-60"
          >
            {saving ? "Saving…" : initial ? "Save changes" : "Add doctor"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
