"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Loader2 } from "lucide-react";
import { api, setToken, getToken, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/overview");
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(username, password);
      setToken(res.access_token);
      router.push("/overview");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 justify-center mb-8">
          <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center">
            <Sparkles size={18} className="text-white" />
          </div>
          <span className="text-lg font-extrabold">Wild Aesthetics</span>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-card rounded-3xl p-8 [box-shadow:var(--shadow-soft)]"
        >
          <p className="text-xl font-bold mb-1">Sign in</p>
          <p className="text-sm text-ink-muted mb-6">
            Access your clinic dashboard
          </p>

          <label className="block text-xs font-semibold text-ink-muted mb-1.5">
            Username
          </label>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full mb-4 px-3.5 py-2.5 rounded-xl border border-border bg-bg text-sm outline-none focus:border-primary transition-colors"
            autoComplete="username"
            required
          />

          <label className="block text-xs font-semibold text-ink-muted mb-1.5">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full mb-5 px-3.5 py-2.5 rounded-xl border border-border bg-bg text-sm outline-none focus:border-primary transition-colors"
            autoComplete="current-password"
            required
          />

          {error && (
            <p className="text-xs text-pink mb-4 bg-pink-soft rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-primary hover:bg-primary-dark transition-colors text-white text-sm font-semibold py-2.5 rounded-xl flex items-center justify-center gap-2 disabled:opacity-60"
          >
            {loading && <Loader2 size={15} className="animate-spin" />}
            Sign in
          </button>
        </form>
      </div>
    </div>
  );
}
