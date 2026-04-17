// LCARS-style status colors
const COLORS: Record<string, string> = {
  idle:              "bg-lcars-panel border border-lcars-muted text-lcars-muted",
  busy:              "bg-lcars-green/20 border border-lcars-green text-lcars-green",
  requested:         "bg-lcars-blue/20 border border-lcars-blue text-lcars-blue",
  planning:          "bg-lcars-amber/20 border border-lcars-amber text-lcars-amber",
  awaiting_approval: "bg-lcars-orange/20 border border-lcars-orange text-lcars-orange",
  in_progress:       "bg-lcars-blue/20 border border-lcars-blue text-lcars-cyan",
  review:            "bg-lcars-purple/20 border border-lcars-purple text-lcars-purple",
  deploying:         "bg-lcars-cyan/20 border border-lcars-cyan text-lcars-cyan",
  done:              "bg-lcars-green/20 border border-lcars-green text-lcars-green",
  rejected:          "bg-lcars-red/20 border border-lcars-red text-lcars-red",
  failed:            "bg-lcars-red/20 border border-lcars-red text-lcars-red",
  pending:           "bg-lcars-panel border border-lcars-muted text-lcars-muted",
  assigned:          "bg-lcars-blue/20 border border-lcars-blue text-lcars-blue",
  completed:         "bg-lcars-amber/20 border border-lcars-amber text-lcars-amber",
  blocked:           "bg-lcars-red/20 border border-lcars-red text-lcars-red",
  active:            "bg-lcars-green/20 border border-lcars-green text-lcars-green",
  paused:            "bg-lcars-amber/20 border border-lcars-amber text-lcars-amber",
  abandoned:         "bg-lcars-panel border border-lcars-border text-lcars-muted",
  archived:          "bg-lcars-panel border border-lcars-border text-lcars-muted",
};

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  const color = COLORS[status] ?? "bg-lcars-panel border border-lcars-border text-lcars-muted";
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-mono font-bold tracking-widest uppercase ${color}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
