"use client";

import { createContext, useContext } from "react";
import type { BotSummary } from "./api";

export interface DashboardContextValue {
  username: string;
  bot: BotSummary;
  refreshBot: () => Promise<void>;
}

export const DashboardContext = createContext<DashboardContextValue | null>(null);

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error("useDashboard() must be used within the dashboard layout");
  }
  return ctx;
}
