import { formatRelativeTime } from "@/lib/utils";

interface ActivityItem {
  agent?: string;
  content?: string;
  role?: string;
  created_at?: string;
  [key: string]: unknown;
}

interface Props {
  items: ActivityItem[];
}

export default function ActivityFeed({ items }: Props) {
  if (items.length === 0) {
    return <div className="text-sm text-gray-400 py-4">No recent activity</div>;
  }

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex gap-3 text-sm border-b border-gray-100 pb-2">
          <div className="shrink-0">
            <span className="inline-block w-6 h-6 bg-gray-200 rounded-full text-center text-xs leading-6 font-medium">
              {(item.agent ?? "?")[0]?.toUpperCase()}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-800">{item.agent}</span>
              {item.role && (
                <span className="text-xs text-gray-400">{item.role}</span>
              )}
              {item.created_at && (
                <span className="text-xs text-gray-400 ml-auto">
                  {formatRelativeTime(item.created_at)}
                </span>
              )}
            </div>
            <p className="text-gray-600 truncate">{item.content}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
