const STYLES: Record<string, string> = {
  Confirmed: "bg-emerald-soft text-emerald",
  Completed: "bg-emerald-soft text-emerald",
  Pending: "bg-amber-soft text-amber",
  Scheduled: "bg-amber-soft text-amber",
  Cancelled: "bg-pink-soft text-pink",
  Rescheduled: "bg-primary-soft text-primary-dark",
};

export function StatusPill({ status }: { status: string }) {
  const cls = STYLES[status] ?? "bg-bg text-ink-muted";
  return (
    <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full ${cls}`}>
      {status}
    </span>
  );
}
