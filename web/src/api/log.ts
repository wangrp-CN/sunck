/** 系统日志 API 封装。
 *
 * 系统日志记录应用运行时的异常、警告与关键事件。
 * 支持分页查询、筛选与 CSV 导出。
 */
import { http } from "@/utils/request";

export interface SystemLogItem {
  id: number;
  level: string;
  module: string;
  message: string;
  detail: string | null;
  traceback: string | null;
  source: string | null;
  user_id: number | null;
  created_at: string | null;
}

export interface SystemLogPage {
  total: number;
  items: SystemLogItem[];
  page: number;
  size: number;
}

export interface SystemLogMeta {
  levels: string[];
  modules: string[];
}

export interface SystemLogListParams {
  page?: number;
  size?: number;
  level?: string;
  module?: string;
  keyword?: string;
  start?: string;
  end?: string;
}

/** 分页查询系统日志 */
export function fetchSystemLogs(params: SystemLogListParams = {}): Promise<SystemLogPage> {
  return http<SystemLogPage>({
    url: "/v1/logs",
    method: "GET",
    params,
  });
}

/** 获取系统日志元数据（级别/模块下拉选项） */
export function fetchSystemLogMeta(): Promise<SystemLogMeta> {
  return http<SystemLogMeta>({
    url: "/v1/logs/meta",
    method: "GET",
  });
}

/** 导出系统日志为 CSV 文件 */
export function exportSystemLogs(params: Omit<SystemLogListParams, "page" | "size"> = {}): void {
  const query = new URLSearchParams();
  if (params.level) query.set("level", params.level);
  if (params.module) query.set("module", params.module);
  if (params.keyword) query.set("keyword", params.keyword);
  if (params.start) query.set("start", params.start);
  if (params.end) query.set("end", params.end);

  // 通过 window.open 触发浏览器下载
  window.open(`/api/v1/logs/export?${query.toString()}`, "_blank");
}
