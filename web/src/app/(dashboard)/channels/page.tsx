"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Check, AlertCircle } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";

interface FieldDef {
  key: string;
  label: string;
  placeholder: string;
  secret?: boolean;
}

function ChannelCard({
  title,
  description,
  active,
  fields,
  values,
  delay,
  onSave,
}: {
  title: string;
  description: string;
  active: boolean;
  fields: FieldDef[];
  values: Record<string, string>;
  delay: number;
  onSave: (vals: Record<string, string>) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]"
    >
      <div className="flex items-center justify-between mb-1">
        <p className="text-[14px] font-bold">{title}</p>
        {active ? (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald bg-emerald-soft px-2 py-1 rounded-full">
            <Check size={11} /> Active
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-amber bg-amber-soft px-2 py-1 rounded-full">
            <AlertCircle size={11} /> Needs setup
          </span>
        )}
      </div>
      <p className="text-[12px] text-ink-muted mb-3">{description}</p>

      {!editing && (
        <button
          onClick={() => {
            setDraft(values);
            setEditing(true);
          }}
          className="text-[12px] font-semibold text-primary border border-primary/30 rounded-lg px-3 py-1.5 hover:bg-primary-soft transition-colors"
        >
          {active ? "Update credentials" : "Connect"}
        </button>
      )}

      {editing && (
        <div className="flex flex-col gap-2.5">
          {fields.map((f) => (
            <div key={f.key}>
              <label className="block text-[11px] font-semibold text-ink-muted mb-1">
                {f.label}
              </label>
              <input
                type={f.secret ? "password" : "text"}
                placeholder={f.placeholder}
                value={draft[f.key] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary transition-colors"
              />
            </div>
          ))}
          <div className="flex gap-2 mt-1">
            <button
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                await onSave(draft);
                setSaving(false);
                setEditing(false);
              }}
              className="text-[12px] font-semibold bg-primary text-white rounded-lg px-3 py-1.5 disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="text-[12px] font-semibold text-ink-muted px-3 py-1.5"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </motion.div>
  );
}

export default function ChannelsPage() {
  const { bot, refreshBot } = useDashboard();

  async function save(fields: Record<string, string>) {
    await api.updateBot(bot.id, fields);
    await refreshBot();
  }

  const isWwebjs = bot.provider === "wwebjs";

  return (
    <>
      <PageHeader title="Channels" subtitle="Connect WhatsApp, Messenger, Instagram, and ManyChat" />

      <div className="grid grid-cols-2 gap-3.5">
        <ChannelCard
          title="WhatsApp"
          description={
            isWwebjs
              ? "Connected via your own number (QR session) — manage from Bot settings."
              : "Meta Cloud API — official WhatsApp Business number."
          }
          active={Boolean(bot.waba_id || bot.wwebjs_session)}
          delay={0}
          fields={
            isWwebjs
              ? []
              : [
                  { key: "waba_id", label: "WABA ID", placeholder: "WhatsApp Business Account ID" },
                  { key: "phone_number_id", label: "Phone number ID", placeholder: "Phone number ID" },
                  { key: "meta_token", label: "Meta access token", placeholder: "EAAG...", secret: true },
                ]
          }
          values={{
            waba_id: bot.waba_id ?? "",
            phone_number_id: bot.phone_number_id ?? "",
          }}
          onSave={save}
        />

        <ChannelCard
          title="Messenger"
          description="Facebook Page connection for Messenger DMs."
          active={Boolean(bot.messenger_page_id)}
          delay={0.05}
          fields={[
            { key: "messenger_page_id", label: "Page ID", placeholder: "Facebook Page ID" },
            { key: "messenger_token", label: "Page access token", placeholder: "EAAG...", secret: true },
          ]}
          values={{ messenger_page_id: bot.messenger_page_id ?? "" }}
          onSave={save}
        />

        <ChannelCard
          title="Instagram"
          description="Instagram Business account connection for DMs."
          active={Boolean(bot.instagram_account_id)}
          delay={0.1}
          fields={[
            { key: "instagram_account_id", label: "Instagram account ID", placeholder: "17841..." },
            { key: "instagram_token", label: "Access token", placeholder: "EAAG...", secret: true },
          ]}
          values={{ instagram_account_id: bot.instagram_account_id ?? "" }}
          onSave={save}
        />

        <ChannelCard
          title="ManyChat"
          description="Bridges Instagram/Messenger replies through ManyChat's Public API."
          active={Boolean(bot.manychat_api_key)}
          delay={0.15}
          fields={[
            { key: "manychat_api_key", label: "ManyChat API key", placeholder: "Profile Scoped Public API key", secret: true },
          ]}
          values={{}}
          onSave={save}
        />
      </div>
    </>
  );
}
