"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { api, getToken, type BotSummary } from "@/lib/api";

export interface DashboardContext {
  username: string;
  bot: BotSummary;
}

export function DashboardShell({
  children,
}: {
  children: (ctx: DashboardContext) => React.ReactNode;
}) {
  const router = useRouter();
  const [ctx, setCtx] = useState<DashboardContext | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    (async () => {
      try {
        const [me, bots] = await Promise.all([api.me(), api.bots()]);
        const bot = bots.find((b) => b.bot_type === "appointment") ?? bots[0];
        if (!bot) {
          setError("No clinic bot found on this account yet.");
          return;
        }
        setCtx({ username: me.username, bot });
      } catch {
        router.replace("/");
      }
    })();
  }, [router]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-ink-muted">
        {error}
      </div>
    );
  }

  if (!ctx) {
    return <div className="min-h-screen" />;
  }

  return (
    <div className="min-h-screen flex">
      <Sidebar username={ctx.username} />
      <main className="flex-1 px-7 py-6 max-w-[1280px]">{children(ctx)}</main>
    </div>
  );
}
