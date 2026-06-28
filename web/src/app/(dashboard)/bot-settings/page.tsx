"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";

function Field({
  label,
  value,
  onChange,
  textarea,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  textarea?: boolean;
}) {
  return (
    <div className="mb-4">
      <label className="block text-[12px] font-semibold text-ink-muted mb-1.5">{label}</label>
      {textarea ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-bg text-[13px] outline-none focus:border-primary transition-colors resize-none"
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3.5 py-2.5 rounded-xl border border-border bg-bg text-[13px] outline-none focus:border-primary transition-colors"
        />
      )}
    </div>
  );
}

export default function BotSettingsPage() {
  const { bot, refreshBot } = useDashboard();
  const [name, setName] = useState(bot.name);
  const [businessName, setBusinessName] = useState(bot.business_name);
  const [language, setLanguage] = useState(bot.language ?? "English");
  const [systemPrompt, setSystemPrompt] = useState(bot.system_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    await api.updateBot(bot.id, {
      name,
      business_name: businessName,
      language,
      system_prompt: systemPrompt,
    });
    await refreshBot();
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  return (
    <>
      <PageHeader title="Bot settings" subtitle="Identity and behavior for your clinic bot" />

      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)] max-w-xl"
      >
        <Field label="Bot name" value={name} onChange={setName} />
        <Field label="Business name" value={businessName} onChange={setBusinessName} />
        <Field label="Language" value={language} onChange={setLanguage} />
        <Field
          label="System prompt (how the AI should behave)"
          value={systemPrompt}
          onChange={setSystemPrompt}
          textarea
        />

        <div className="flex items-center gap-3 mt-2">
          <button
            disabled={saving}
            onClick={handleSave}
            className="bg-primary hover:bg-primary-dark transition-colors text-white text-[13px] font-semibold px-4 py-2.5 rounded-xl disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          {saved && <span className="text-[12px] text-emerald font-semibold">Saved</span>}
        </div>
      </motion.div>
    </>
  );
}
