"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { UserPlus, Trash2, Shield } from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { PageHeader } from "@/components/PageHeader";
import { api, ApiError } from "@/lib/api";

interface TeamMember {
  user_id: number;
  username: string;
  role: "owner" | "member";
}

export default function TeamPage() {
  const { bot } = useDashboard();
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api.team(bot.id).then((rows) => {
      setMembers(rows);
      setLoading(false);
    });
  }

  useEffect(load, [bot.id]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await api.addTeamMember(bot.id, username, password);
      setUsername("");
      setPassword("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add user.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(userId: number) {
    await api.removeTeamMember(bot.id, userId);
    setMembers((prev) => prev.filter((m) => m.user_id !== userId));
  }

  return (
    <>
      <PageHeader
        title="Team"
        subtitle="Add staff logins — new accounts always get regular 'user' access, never admin"
      />

      <div className="grid grid-cols-[1fr_1.2fr] gap-3.5">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-[13.5px] font-bold mb-3 flex items-center gap-2">
            <UserPlus size={16} /> Add a team member
          </p>
          <form onSubmit={handleAdd} className="flex flex-col gap-2.5">
            <div>
              <label className="block text-[11px] font-semibold text-ink-muted mb-1">
                Username
              </label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary transition-colors"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-ink-muted mb-1">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full px-3 py-2 rounded-lg border border-border bg-bg text-[12.5px] outline-none focus:border-primary transition-colors"
              />
            </div>
            {error && (
              <p className="text-[11.5px] text-pink bg-pink-soft rounded-lg px-3 py-2">{error}</p>
            )}
            <button
              type="submit"
              disabled={saving}
              className="bg-primary hover:bg-primary-dark transition-colors text-white text-[12.5px] font-semibold py-2 rounded-lg disabled:opacity-60 mt-1"
            >
              {saving ? "Adding…" : "Add to team"}
            </button>
            <p className="text-[11px] text-ink-faint">
              If that username already exists, they just get added to this bot — no new login is created.
            </p>
          </form>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="bg-card rounded-2xl p-5 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-[13.5px] font-bold mb-3">Who has access</p>
          {loading && <p className="text-sm text-ink-muted py-6 text-center">Loading…</p>}
          {!loading &&
            members.map((m, i) => (
              <motion.div
                key={m.user_id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.04 }}
                className="flex items-center gap-3 py-2.5 border-b border-border last:border-0"
              >
                <div className="w-8 h-8 rounded-full bg-primary-soft flex items-center justify-center text-[11px] font-bold text-primary-dark shrink-0">
                  {m.username.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1">
                  <p className="text-[13px] font-semibold">{m.username}</p>
                </div>
                {m.role === "owner" ? (
                  <span className="flex items-center gap-1 text-[11px] font-semibold text-primary-dark bg-primary-soft px-2.5 py-1 rounded-full">
                    <Shield size={11} /> Owner
                  </span>
                ) : (
                  <button
                    onClick={() => handleRemove(m.user_id)}
                    className="text-pink hover:bg-pink-soft transition-colors p-1.5 rounded-lg"
                    aria-label={`Remove ${m.username}`}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </motion.div>
            ))}
        </motion.div>
      </div>
    </>
  );
}
