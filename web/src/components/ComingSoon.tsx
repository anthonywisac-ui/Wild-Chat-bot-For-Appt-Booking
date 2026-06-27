"use client";

import { DashboardShell } from "./DashboardShell";

export function ComingSoonPage({ title }: { title: string }) {
  return (
    <DashboardShell>
      {() => (
        <div className="h-[70vh] flex flex-col items-center justify-center text-center">
          <h1 className="text-lg font-bold mb-1">{title}</h1>
          <p className="text-sm text-ink-muted">This page is coming soon.</p>
        </div>
      )}
    </DashboardShell>
  );
}
