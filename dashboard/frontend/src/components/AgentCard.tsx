import { useQuery } from "@tanstack/react-query";
import type { AgentSummary } from "@/lib/types";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import StatusBadge from "./StatusBadge";

const TASK_STATUS_STYLE: Record<string, string> = {
  in_progress: "text-blue-700 bg-blue-50",
  assigned: "text-yellow-700 bg-yellow-50",
  pending: "text-gray-600 bg-gray-100",
};

const TASK_STATUS_DOT: Record<string, string> = {
  in_progress: "bg-blue-500",
  assigned: "bg-yellow-400",
  pending: "bg-gray-400",
};

interface Props {
  agent: AgentSummary;
}

export default function AgentCard({ agent }: Props) {
  const activity = useQuery({
    queryKey: ["agentActivity", agent.persona_name],
    queryFn: () => api.getAgentActivity(agent.persona_name, 6),
    staleTime: 30_000,
  });

  // Keep only assistant turns, last 3.
  const recentMessages = (activity.data ?? [])
    .filter((m) => m["role"] === "assistant")
    .slice(0, 3);

  return (
    <div className="bg-white rounded-lg border p-4 hover:shadow-md transition-shadow flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm">{agent.persona_name}</h3>
        <StatusBadge status={agent.status} />
      </div>

      {/* Meta */}
      <div className="text-xs text-gray-500 flex gap-4">
        <span>Model: <span className="text-gray-700">{agent.model}</span></span>
        <span>Cost: <span className="text-gray-700">{formatCurrency(agent.total_cost_usd)}</span></span>
      </div>

      {!agent.enabled && (
        <div className="text-xs text-red-600">Disabled</div>
      )}

      {/* Active tasks */}
      {(agent.active_tasks?.length ?? 0) > 0 && (
        <div>
          <div className="text-xs font-medium text-gray-500 mb-1">Active tasks</div>
          <ul className="space-y-1">
            {agent.active_tasks.map((task) => {
              const style = TASK_STATUS_STYLE[task.status] ?? "text-gray-600 bg-gray-100";
              const dot = TASK_STATUS_DOT[task.status] ?? "bg-gray-400";
              return (
                <li
                  key={task.task_id}
                  className={`text-xs rounded px-2 py-1 flex items-start gap-1.5 ${style}`}
                >
                  <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
                  <span>
                    <span className="font-medium">{task.title}</span>
                    <span className="text-[10px] opacity-70 ml-1">— {task.feature_title}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Recent activity */}
      <div>
        <div className="text-xs font-medium text-gray-500 mb-1">Recent activity</div>
        {activity.isLoading ? (
          <div className="text-xs text-gray-400">Loading...</div>
        ) : recentMessages.length === 0 ? (
          <div className="text-xs text-gray-400 italic">No recent activity</div>
        ) : (
          <ul className="space-y-1">
            {recentMessages.map((m, i) => {
              const content = String(m["content"] ?? "");
              const preview = content.length > 80 ? content.slice(0, 80) + "…" : content;
              return (
                <li key={i} className="text-xs text-gray-600 bg-gray-50 rounded px-2 py-1 truncate">
                  {preview}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
