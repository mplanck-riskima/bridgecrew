import { useQuery } from "@tanstack/react-query";
import { CostBarChart, CostTimelineChart } from "@/components/CostChart";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

export default function Costs() {
  const breakdown = useQuery({
    queryKey: ["costBreakdown"],
    queryFn: api.getCostBreakdown,
  });
  const timeline = useQuery({
    queryKey: ["costTimeline"],
    queryFn: () => api.getCostTimeline(30),
  });

  const modelData = Object.entries(breakdown.data?.by_model ?? {}).map(
    ([name, value]) => ({ name, value }),
  );
  const projectData = Object.entries(breakdown.data?.by_project ?? {}).map(
    ([name, value]) => ({ name, value }),
  );
  const categoryData = Object.entries(breakdown.data?.by_category ?? {}).map(
    ([name, value]) => ({ name, value }),
  );

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

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="w-1 h-6 bg-lcars-orange" />
        <h1 className="text-lcars-orange font-mono text-xs tracking-[0.3em] uppercase">
          Resource Allocation
        </h1>
      </div>

      <LcarsPanel label="Total Resource Expenditure">
        <div className="text-4xl font-mono text-lcars-amber">
          {breakdown.isLoading ? "..." : formatCurrency(breakdown.data?.total_usd ?? 0)}
        </div>
      </LcarsPanel>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <LcarsPanel label="Stardate Timeline — 30 Days">
          {timeline.isLoading ? (
            <div className="text-lcars-muted font-mono text-sm animate-pulse">── RETRIEVING ──</div>
          ) : (
            <CostTimelineChart data={timeline.data ?? []} title="" />
          )}
        </LcarsPanel>
        <LcarsPanel label="By Model">
          {breakdown.isLoading ? (
            <div className="text-lcars-muted font-mono text-sm animate-pulse">── RETRIEVING ──</div>
          ) : (
            <CostBarChart data={modelData} title="" />
          )}
        </LcarsPanel>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <LcarsPanel label="By Project">
          {breakdown.isLoading ? (
            <div className="text-lcars-muted font-mono text-sm animate-pulse">── RETRIEVING ──</div>
          ) : (
            <CostBarChart data={projectData} title="" />
          )}
        </LcarsPanel>
        <LcarsPanel label="By Category">
          {breakdown.isLoading ? (
            <div className="text-lcars-muted font-mono text-sm animate-pulse">── RETRIEVING ──</div>
          ) : (
            <CostBarChart data={categoryData} title="" />
          )}
        </LcarsPanel>
      </div>
    </div>
  );
}
