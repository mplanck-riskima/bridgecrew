/** Typed fetch wrapper for the dashboard API. */

import type {
  ActivityEntry,
  AgentSummary,
  CostBreakdown,
  CostTimelineEntry,
  Feature,
  PaginatedResponse,
  PersonaDefinition,
  Project,
  PromptTemplate,
  ScheduledTask,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // Features
  getFeatures: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<PaginatedResponse<Feature>>(`/features${qs}`);
  },
  getFeature: (id: string) => request<Feature>(`/features/${id}`),
  deleteFeature: (id: string) =>
    request<void>(`/features/${id}`, { method: "DELETE" }),

  // Prompt templates
  getPrompts: () => request<PromptTemplate[]>("/prompts"),
  createPrompt: (data: { name: string; description?: string; content: string }) =>
    request<PromptTemplate>("/prompts", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updatePrompt: (id: string, data: Partial<PromptTemplate>) =>
    request<PromptTemplate>(`/prompts/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deletePrompt: (id: string) =>
    request<void>(`/prompts/${id}`, { method: "DELETE" }),

  // Scheduled tasks
  getSchedules: () => request<ScheduledTask[]>("/schedules"),
  createSchedule: (data: Omit<ScheduledTask, "id" | "last_run" | "last_status">) =>
    request<ScheduledTask>("/schedules", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateSchedule: (id: string, data: Partial<ScheduledTask>) =>
    request<ScheduledTask>(`/schedules/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteSchedule: (id: string) =>
    request<void>(`/schedules/${id}`, { method: "DELETE" }),
  triggerSchedule: (id: string) =>
    request<{ status: string; channel_id: string }>(`/schedules/${id}/trigger`, {
      method: "POST",
    }),

  // Costs
  getCostBreakdown: () => request<CostBreakdown>("/costs/breakdown"),
  getCostTimeline: (days = 30) =>
    request<CostTimelineEntry[]>(`/costs/timeline?days=${days}`),
  getCostsByAgent: (agent?: string) => {
    const qs = agent ? `?agent=${agent}` : "";
    return request<Record<string, unknown>[]>(`/costs/by-agent${qs}`);
  },

  // Activity feed
  getProjectActivity: (projectId: string, limit = 50) =>
    request<ActivityEntry[]>(`/projects/${projectId}/activity?limit=${limit}`),

  // Agents
  getAgents: () => request<AgentSummary[]>("/agents"),
  getAgentActivity: (agentName: string, limit = 30) =>
    request<ActivityEntry[]>(`/agents/${encodeURIComponent(agentName)}/activity?limit=${limit}`),

  // Personas
  getPersonas: () => request<PersonaDefinition[]>("/personas"),
  updatePersona: (name: string, data: Partial<PersonaDefinition>) =>
    request<PersonaDefinition>(`/personas/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  resetPersona: (name: string) =>
    request<PersonaDefinition>(`/personas/${encodeURIComponent(name)}/reset`, {
      method: "POST",
    }),

  // Memory
  getShortTermMemories: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<PaginatedResponse<Record<string, unknown>>>(`/memory/short-term${qs}`);
  },
  getLongTermMemories: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<PaginatedResponse<Record<string, unknown>>>(`/memory/long-term${qs}`);
  },
  searchMemories: (query: string) =>
    request<PaginatedResponse<Record<string, unknown>>>(
      `/memory/search?q=${encodeURIComponent(query)}`,
    ),

  // Projects
  getProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (data: { name: string; description?: string }) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateProject: (id: string, data: Partial<Project>) =>
    request<Project>(`/projects/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),
};
