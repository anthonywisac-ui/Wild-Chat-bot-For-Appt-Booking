"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { Modal } from "./Modal";
import { api, type Procedure, type ProcedurePayload, DEPARTMENT_LABELS } from "@/lib/api";

export function ProcedureFormModal({
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
  initial?: Procedure;
  onSaved: (p: Procedure) => void;
  onDeleted?: (id: number) => void;
}) {
  const [form, setForm] = useState<ProcedurePayload>(
    initial
      ? {
          department: initial.department,
          name: initial.name,
          sessions_required: initial.sessions_required,
          fee_per_session: initial.fee_per_session,
          package_tier: initial.package_tier ?? "",
          description: initial.description ?? "",
        }
      : { department: "skin", name: "", sessions_required: 1, fee_per_session: 0, package_tier: "", description: "" }
  );
  const [saving, setSaving] = useState(false);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const result = initial
        ? await api.updateProcedure(botId, initial.id, form)
        : await api.createProcedure(botId, form);
      onSaved(result);
      onClose();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!initial) return;
    await api.deleteProcedure(botId, initial.id);
    onDeleted?.(initial.id);
    onClose();
  }

  return (
    <Modal open={open} onClose={onClose} title={initial ? "Edit treatment" : "Add treatment"}>
      <form onSubmit={handleSave} className="flex flex-col gap-2.5">
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
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Sessions</label>
            <input
              type="number"
              min={1}
              required
              value={form.sessions_required}
              onChange={(e) => setForm((f) => ({ ...f, sessions_required: Number(e.target.value) }))}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink-muted mb-1">Fee per session ($)</label>
            <input
              type="number"
              min={0}
              required
              value={form.fee_per_session}
              onChange={(e) => setForm((f) => ({ ...f, fee_per_session: Number(e.target.value) }))}
              className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary"
            />
          </div>
        </div>
        <div>
          <label className="block text-[11px] font-semibold text-ink-muted mb-1">Description (optional)</label>
          <textarea
            rows={2}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary resize-none"
          />
        </div>

        <div className="flex items-center justify-between mt-1.5">
          {initial ? (
            <button
              type="button"
              onClick={handleDelete}
              className="text-pink hover:bg-pink-soft transition-colors p-1.5 rounded-lg"
              aria-label="Delete treatment"
            >
              <Trash2 size={15} />
            </button>
          ) : <span />}
          <button
            type="submit"
            disabled={saving}
            className="bg-primary hover:bg-primary-dark transition-colors text-white text-[12.5px] font-semibold px-4 py-2 rounded-lg disabled:opacity-60"
          >
            {saving ? "Saving…" : initial ? "Save changes" : "Add treatment"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
