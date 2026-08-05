// 操作审计 API 封装（列表检索 + 元数据）
import { http } from "@/utils/request";

export type AuditAction = "create" | "update" | "delete" | "other";

export interface AuditLogItem {
  id: number;
  user_id: number | null;
  username: string | null;
  dept_id: number | null;
  action: string;
  module: string;
  method: string;
  path: string;
  query: string | null;
  status_code: number;
  ip: string | null;
  detail: string | null;
  created_at: string | null;
}

export interface AuditLogPage {
  total: number;
  items: AuditLogItem[];
  page: number;
  size: number;
}

export interface AuditListParams {
  page?: number;
  size?: number;
  module?: string;
  action?: string;
  username?: string;
  start?: string;
  end?: string;
}

export interface AuditMeta {
  modules: string[];
  actions: string[];
}

export function fetchAuditLogs(params: AuditListParams = {}): Promise<AuditLogPage> {
  return http<AuditLogPage>({
    url: "/v1/audit-logs",
    method: "GET",
    params,
  });
}

export function fetchAuditMeta(): Promise<AuditMeta> {
  return http<AuditMeta>({
    url: "/v1/audit-logs/meta",
    method: "GET",
  });
}

/** 导出审计日志为 CSV 文件 */
export function exportAuditLogs(params: Omit<AuditListParams, "page" | "size"> = {}): void {
  const query = new URLSearchParams();
  if (params.module) query.set("module", params.module);
  if (params.action) query.set("action", params.action);
  if (params.username) query.set("username", params.username);
  if (params.start) query.set("start", params.start);
  if (params.end) query.set("end", params.end);
  window.open(`/api/v1/audit-logs/export?${query.toString()}`, "_blank");
}
