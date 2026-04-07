import cronstrue from "cronstrue";
import { useState } from "react";

const PRESETS = [
  { label: "Hourly",         value: "0 * * * *" },
  { label: "Daily 9 AM",     value: "0 9 * * *" },
  { label: "Daily Midnight", value: "0 0 * * *" },
  { label: "Mon 9 AM",       value: "0 9 * * 1" },
  { label: "Monthly 1st",    value: "0 9 1 * *" },
];

interface Props {
  value: string;
  onChange: (val: string) => void;
  className?: string;
}

function describeOrError(expr: string): { preview: string; error: string } {
  if (!expr.trim()) return { preview: "", error: "" };
  try {
    return { preview: cronstrue.toString(expr, { use24HourTimeFormat: false }), error: "" };
  } catch {
    return { preview: "", error: "Invalid cron expression" };
  }
}

export default function CronInput({ value, onChange, className = "" }: Props) {
  const [focused, setFocused] = useState(false);
  const { preview, error } = describeOrError(value);

  const inputCls =
    "w-full bg-lcars-panel border text-lcars-text font-mono text-sm px-3 py-2 focus:outline-none placeholder:text-lcars-muted " +
    (error ? "border-lcars-red" : focused ? "border-lcars-orange" : "border-lcars-border");

  return (
    <div className={className}>
      {/* Preset buttons */}
      <div className="flex flex-wrap gap-1 mb-2">
        {PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            onClick={() => onChange(p.value)}
            className={
              "px-2 py-0.5 text-xs font-mono tracking-widest border transition-colors " +
              (value === p.value
                ? "bg-lcars-orange text-black border-lcars-orange"
                : "border-lcars-border text-lcars-muted hover:border-lcars-orange hover:text-lcars-orange")
            }
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Raw input */}
      <input
        className={inputCls}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder="0 9 * * *"
        spellCheck={false}
      />

      {/* Live preview / error */}
      <div className="mt-1 text-xs font-mono h-4">
        {error ? (
          <span className="text-lcars-red">{error}</span>
        ) : preview ? (
          <span className="text-lcars-muted">{preview}</span>
        ) : null}
      </div>
    </div>
  );
}
