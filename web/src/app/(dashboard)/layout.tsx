"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Sidebar } from "@/components/Sidebar";
import { DashboardContext } from "@/lib/dashboard-context";
import { api, getToken, type BotSummary } from "@/lib/api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [username, setUsername] = useState<string | null>(null);
  const [bot, setBot] = useState<BotSummary | null>(null);
  const [leadCount, setLeadCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const loadBot = useCallback(async () => {
    const bots = await api.bots();
    const found = bots.find((b) => b.bot_type === "appointment") ?? bots[0];
    if (!found) {
      setError("No clinic bot found on this account yet.");
      return;
    }
    setBot(found);
    try {
      const leads = await api.leads(found.id);
      setLeadCount(leads.filter((l) => l.status === "new").length);
    } catch {
      // non-fatal — badge just stays at 0
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    (async () => {
      try {
        const me = await api.me();
        setUsername(me.username);
        await loadBot();
      } catch {
        router.replace("/");
      }
    })();
  }, [router, loadBot]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-ink-muted">
        {error}
      </div>
    );
  }

  if (!username || !bot) {
    return <div className="min-h-screen" />;
  }

  return (
    <DashboardContext.Provider value={{ username, bot, refreshBot: loadBot }}>
      <div className="min-h-screen flex">
        <Sidebar username={username} leadCount={leadCount} />
        <main className="flex-1 px-7 py-6 max-w-[1280px] overflow-x-hidden">
          <AnimatePresence mode="wait">
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.18, ease: "easeOut" }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </DashboardContext.Provider>
  );
}
