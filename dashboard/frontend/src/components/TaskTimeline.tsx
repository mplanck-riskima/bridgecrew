import { useState } from "react";
import type { Task } from "@/lib/types";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import StatusBadge from "./StatusBadge";

interface Props {
  tasks: Task[];
}

export default function TaskTimeline({ tasks }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (tasks.length === 0) {
    return <div className="text-sm text-gray-400 py-4">No tasks</div>;
  }

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div className="space-y-3">
      {tasks.map((task) => {
        const hasOutput = !!task.last_output;
        const isFailed = task.status === "failed";
        const isOpen = expanded.has(task.task_id);

        return (
          <div
            key={task.task_id}
            className={`flex items-start gap-3 bg-white border rounded-lg p-3 ${
              isFailed ? "border-red-200" : ""
            }`}
          >
            <div
              className={`w-1 rounded shrink-0 self-stretch ${
                isFailed ? "bg-red-400" : "bg-gray-200"
              }`}
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-sm">{task.title}</span>
                <StatusBadge status={task.status} />
              </div>
              <div className="text-xs text-gray-500 space-x-3">
                <span>Assigned: {task.assigned_to || "unassigned"}</span>
                <span>Cost: {formatCurrency(task.cost_usd)}</span>
                <span>{formatDateTime(task.created_at)}</span>
              </div>
              {task.description && (
                <p className="text-xs text-gray-600 mt-1 truncate">
                  {task.description}
                </p>
              )}
              {task.pr_url && (
                <a
                  href={task.pr_url}
                  className="text-xs text-blue-600 hover:underline mt-1 inline-block"
                  target="_blank"
                  rel="noreferrer"
                >
                  PR
                </a>
              )}
              {hasOutput && (
                <div className="mt-2">
                  <button
                    onClick={() => toggle(task.task_id)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    {isOpen ? "▼ Hide output" : "▶ Show last output"}
                  </button>
                  {isOpen && (
                    <pre
                      className={`mt-1 text-xs whitespace-pre-wrap break-words rounded p-2 max-h-64 overflow-y-auto font-mono ${
                        isFailed
                          ? "bg-red-50 text-red-800"
                          : "bg-gray-50 text-gray-700"
                      }`}
                    >
                      {task.last_output}
                    </pre>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
