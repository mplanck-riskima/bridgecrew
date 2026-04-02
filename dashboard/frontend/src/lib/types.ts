/** TypeScript interfaces mirroring backend models. */

export interface Feature {
  feature_id: string;
  project_id: string;
  name: string;
  description: string;
  status: "active" | "completed" | "abandoned";
  session_id: string;
  prompt_template_id: string;
  subdir: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  summary: string | null;
  git_branch: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  content: string;
  updated_at: string;
}

export interface ScheduledTask {
  id: string;
  name: string;
  project_id: string;
  prompt_template_id: string;
  discord_channel_id: string;
  cron_expr: string;
  enabled: boolean;
  last_run: string | null;
  last_status: "dispatched" | "failed" | "skipped" | "unknown";
}

export interface Project {
  project_id: string;
  name: string;
  description: string;
  status: string;
  prompt_template_id: string | null;
  created_at: string;
  updated_at: string;
  features?: Feature[];
  total_cost_usd?: number;
  feature_count?: number;
}

export interface CostBreakdown {
  total_usd: number;
  by_agent: Record<string, number>;
  by_project: Record<string, number>;
  by_model: Record<string, number>;
  by_category: Record<string, number>;
}

export interface CostTimelineEntry {
  date: string;
  total: number;
  count: number;
}

export interface ActivityEntry {
  activity_id: string;
  project_id: string;
  role: "user" | "assistant";
  author: string;
  content: string;
  feature_name: string | null;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
