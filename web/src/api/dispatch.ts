import { http } from "@/utils/request";

export interface DispatchOrder {
  id: number;
  project_id: number | null;
  source_type: string;
  source_id: number | null;
  title: string;
  root_cause_hint: string | null;
  level: string | null;
  status: string;
  assignee_id: number | null;
  assignee_name: string | null;
  deadline: string | null;
  description: string | null;
  last_action_note: string | null;
  closed_at: string | null;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DispatchPage {
  total: number;
  items: DispatchOrder[];
  page: number;
  size: number;
}

export interface DispatchStats {
  total: number;
  by_status: Record<string, number>;
  by_level: Record<string, number>;
}

export interface DispatchOptions {
  statuses: string[];
  sources: string[];
  levels: string[];
}

export interface DispatchPreset {
  source_type: string;
  source_id?: number | null;
  project_id?: number | null;
  title?: string;
  root_cause_hint?: string | null;
  level?: string | null;
}

export function getDispatchOptions(): Promise<DispatchOptions> {
  return http<DispatchOptions>({ url: "/v1/dispatch/options", method: "GET" });
}

export function getDispatchStats(): Promise<DispatchStats> {
  return http<DispatchStats>({ url: "/v1/dispatch/stats", method: "GET" });
}

export function listDispatches(params: {
  status?: string;
  source_type?: string;
  project_id?: number;
  page?: number;
  size?: number;
}): Promise<DispatchPage> {
  return http<DispatchPage>({ url: "/v1/dispatch/", method: "GET", params });
}

export function getDispatch(id: number): Promise<DispatchOrder> {
  return http<DispatchOrder>({ url: `/v1/dispatch/${id}`, method: "GET" });
}

export function createDispatch(data: {
  title: string;
  source_type?: string;
  source_id?: number | null;
  project_id?: number | null;
  level?: string | null;
  root_cause_hint?: string | null;
  assignee_id?: number | null;
  deadline?: string | null;
  description?: string | null;
}): Promise<DispatchOrder> {
  return http<DispatchOrder>({ url: "/v1/dispatch/", method: "POST", data });
}

export function dispatchAction(id: number, action: string, note?: string): Promise<DispatchOrder> {
  return http<DispatchOrder>({ url: `/v1/dispatch/${id}`, method: "PATCH", data: { action, note } });
}

export function reassignDispatch(id: number, assignee_id: number, note?: string): Promise<DispatchOrder> {
  return http<DispatchOrder>({ url: `/v1/dispatch/${id}/reassign`, method: "POST", data: { assignee_id, note } });
}
