import { useState } from "react";
import { formatDateTime } from "@/lib/utils";

interface Props {
  items: Record<string, unknown>[];
}

export default function MemoryInspector({ items }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (items.length === 0) {
    return <div className="text-sm text-gray-400 py-4">No memories found</div>;
  }

  return (
    <div className="space-y-2">
      {items.map((item, i) => {
        const isOpen = expanded === i;
        return (
          <div key={i} className="bg-white border rounded-lg">
            <button
              onClick={() => setExpanded(isOpen ? null : i)}
              className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-gray-50"
            >
              <span className="text-xs font-mono text-gray-400 shrink-0">
                {(item.agent as string) ?? "unknown"}
              </span>
              <span className="text-sm text-gray-700 truncate flex-1">
                {(item.content as string)?.slice(0, 120) ?? JSON.stringify(item).slice(0, 120)}
              </span>
              <span className="text-xs text-gray-400 shrink-0">
                {item.created_at ? formatDateTime(item.created_at as string) : ""}
              </span>
              <span className="text-gray-400">{isOpen ? "\u25B2" : "\u25BC"}</span>
            </button>
            {isOpen && (
              <div className="px-4 pb-3 border-t">
                <pre className="text-xs bg-gray-50 rounded p-3 mt-2 overflow-auto max-h-64 whitespace-pre-wrap">
                  {JSON.stringify(item, null, 2)}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
