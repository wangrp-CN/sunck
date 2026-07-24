// 隐患治理闭环 API 封装
import request, { http } from "@/utils/request";

export type HazardLevel = "重大" | "较大" | "一般" | "低";
export type HazardStatus =
  | "待整改"
  | "整改中"
  | "待复核"
  | "已销号"
  | "已驳回";

export interface Hazard {
  id: number;
  project_id: number | null;
  project_name: string | null;
  title: string;
  level: HazardLevel;
  category: string | null;
  description: string | null;
  location_desc: string | null;
  lng: number | null;
  lat: number | null;
  discovered_by_name: string | null;
  discovered_at: string | null;
  source: string;
  status: HazardStatus;
  assignee_id: number | null;
  assignee_name: string | null;
  due_at: string | null;
  rectify_note: string | null;
  rectify_at: string | null;
  verify_by_name: string | null;
  verify_at: string | null;
  verify_note: string | null;
  closed_at: string | null;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
  is_overdue: boolean;
}

export interface HazardCreate {
  project_id?: number | null;
  title: string;
  level?: HazardLevel;
  category?: string | null;
  description?: string | null;
  location_desc?: string | null;
  lng?: number | null;
  lat?: number | null;
  discovered_by_name?: string | null;
  discovered_at?: string | null;
  source?: string;
  assignee_id?: number | null;
  due_at?: string | null;
}

export type HazardUpdate = Partial<HazardCreate>;

export interface HazardTransition {
  action: string;
  note?: string | null;
}

export interface HazardStats {
  total: number;
  by_status: Record<string, number>;
  by_level: Record<string, number>;
  overdue: number;
}

export interface HazardOptions {
  levels: string[];
  categories: string[];
  sources: string[];
  statuses: string[];
}

export interface HazardPage {
  total: number;
  items: Hazard[];
  page: number;
  size: number;
}

// 分页列表（带筛选 + 数据隔离）
export function fetchHazards(params: {
  project_id?: number;
  level?: string;
  status?: string;
  keyword?: string;
  overdue?: boolean;
  page?: number;
  size?: number;
}): Promise<HazardPage> {
  return http<HazardPage>({ url: "/v1/hazards", method: "GET", params });
}

export function createHazard(req: HazardCreate): Promise<Hazard> {
  return http<Hazard>({ url: "/v1/hazards", method: "POST", data: req });
}

export function updateHazard(id: number, req: HazardUpdate): Promise<Hazard> {
  return http<Hazard>({ url: `/v1/hazards/${id}`, method: "PUT", data: req });
}

export function deleteHazard(id: number): Promise<{ id: number }> {
  return http<{ id: number }>({ url: `/v1/hazards/${id}`, method: "DELETE" });
}

export function transitionHazard(id: number, req: HazardTransition): Promise<Hazard> {
  return http<Hazard>({
    url: `/v1/hazards/${id}/transition`,
    method: "POST",
    data: req,
  });
}

export function fetchHazardStats(): Promise<HazardStats> {
  return http<HazardStats>({ url: "/v1/hazards/stats", method: "GET" });
}

export function fetchHazardOptions(): Promise<HazardOptions> {
  return http<HazardOptions>({ url: "/v1/hazards/options", method: "GET" });
}

// 导出隐患报表（excel|pdf）——返回二进制 Blob
export interface HazardExportParams {
  project_id?: number;
  level?: string;
  status?: string;
  keyword?: string;
  overdue?: boolean;
}
export async function exportHazardReport(
  fmt: "excel" | "pdf",
  params: HazardExportParams,
): Promise<Blob> {
  const resp = await request.get("/v1/hazards/export", {
    params: { ...params, fmt },
    responseType: "blob",
  });
  return resp.data as Blob;
}
