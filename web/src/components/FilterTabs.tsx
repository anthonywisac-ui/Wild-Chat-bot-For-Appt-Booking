export function FilterTabs({
  options,
  value,
  onChange,
}: {
  options: { label: string; value: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-1 bg-bg rounded-xl p-1 mb-4 w-fit">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`text-[12.5px] font-semibold px-3 py-1.5 rounded-lg transition-colors ${
            value === opt.value
              ? "bg-card text-ink [box-shadow:var(--shadow-soft)]"
              : "text-ink-muted hover:text-ink"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
