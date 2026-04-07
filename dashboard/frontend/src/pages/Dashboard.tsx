import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/utils";

function LcarsPanel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-lcars-panel border border-lcars-border">
      <div className="px-3 py-1 border-b border-lcars-border">
        <span className="text-lcars-orange text-xs font-mono tracking-[0.2em] uppercase">{label}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

export default function Dashboard() {
  const costs = useQuery({ queryKey: ["costBreakdown"], queryFn: api.getCostBreakdown });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.getProjects });

  const totalCost = costs.data?.total_usd ?? 0;
  const projectList = projects.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <div className="h-px flex-1 bg-lcars-orange opacity-40" />
        <h1 className="text-lcars-orange font-mono text-xs tracking-[0.3em] uppercase">
          Main Bridge — Status Report
        </h1>
        <div className="h-px flex-1 bg-lcars-orange opacity-40" />
      </div>

      {/* Status panels */}
      <div className="grid grid-cols-1 gap-4">
        <Link to="/costs">
          <LcarsPanel label="Resource Usage">
            <div className="text-4xl font-mono text-lcars-green">
              {costs.isLoading ? "..." : formatCurrency(totalCost)}
            </div>
            <div className="text-lcars-muted text-xs mt-1 font-mono">total compute cost</div>
          </LcarsPanel>
        </Link>
      </div>

      {/* Project roster */}
      <LcarsPanel label="Mission Roster">
        {projects.isLoading ? (
          <div className="text-lcars-muted font-mono text-sm animate-pulse">
            ── RETRIEVING DATA ──
          </div>
        ) : projectList.length === 0 ? (
          <div className="text-lcars-muted font-mono text-sm">NO MISSIONS ON RECORD</div>
        ) : (
          <div className="space-y-0">
            {projectList.map((p, i) => (
              <Link
                key={p.project_id}
                to={`/projects/${p.project_id}`}
                className="flex items-center gap-4 py-2 border-b border-lcars-border/50 last:border-0 hover:bg-lcars-border/20 px-2 -mx-2 transition-colors group"
              >
                <span className="text-lcars-muted font-mono text-xs w-6 shrink-0">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className={`w-2 h-2 rounded-full shrink-0 ${
                  p.status === "active" ? "bg-lcars-green" :
                  p.status === "paused" ? "bg-lcars-amber" : "bg-lcars-muted"
                }`} />
                <span className="flex-1 text-lcars-text group-hover:text-lcars-cyan font-medium transition-colors">
                  {p.name}
                </span>
                {p.total_cost_usd ? (
                  <span className="text-lcars-green font-mono text-xs shrink-0">
                    {formatCurrency(p.total_cost_usd)}
                  </span>
                ) : null}
                <span className="text-lcars-muted font-mono text-xs shrink-0">
                  {formatDate(p.created_at)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </LcarsPanel>

      {/* Cost breakdown by model */}
      {!costs.isLoading && costs.data?.by_model && Object.keys(costs.data.by_model).length > 0 && (
        <LcarsPanel label="Compute by Model">
          <div className="space-y-2">
            {Object.entries(costs.data.by_model)
              .sort(([, a], [, b]) => (b as number) - (a as number))
              .map(([model, cost]) => {
                const pct = totalCost > 0 ? ((cost as number) / totalCost) * 100 : 0;
                return (
                  <div key={model} className="space-y-1">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-lcars-cyan truncate max-w-[60%]">{model}</span>
                      <span className="text-lcars-amber">{formatCurrency(cost as number)}</span>
                    </div>
                    <div className="h-1 bg-lcars-border rounded-full overflow-hidden">
                      <div
                        className="h-full bg-lcars-orange rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
          </div>
        </LcarsPanel>
      )}
    </div>
  );
}
