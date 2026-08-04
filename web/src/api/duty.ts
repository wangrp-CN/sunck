// 值班排班 API 封装（🅱 告警治理与值班体系）
// 后端路由：GET /v1/duty/ 列表；/on-duty 当前值班；/meta 枚举；/{id} 详情
//           POST / 新增；PUT /{id} 编辑；DELETE /{id} 删除（逻辑）
// 约定：http<T> 已解包 data，失败时抛 Error(message)。
import { http } from "@/utils/request";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

/** 单条排班记录（与后端 DutyRosterOut 对齐） */
export interface DutyRoster {
  id: number;
  project_id: number | null;
  user_id: number | null;
  shift: string;
  duty_role: string | null;
  start_time: string; // 北京时间 ISO（naive）
  end_time: string;
  note: string | null;
  user_name: string | null;
  project_name: string | null;
  is_current: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** 分页列表 */
export interface DutyRosterPage {
  total: number;
  items: DutyRoster[];
  page: number;
  size: number;
}

/** 枚举元数据（班次） */
export interface DutyMeta {
  shifts: string[];
}

/** 当前值班查询结果 */
export interface OnDutyResult {
  project_id: number;
  user_id: number | null;
  user_name: string | null;
}

/** 列表查询参数 */
export interface DutyListParams {
  project_id?: number;
  user_id?: number;
  active?: boolean;
  page?: number;
  size?: number;
}

/** 新建/编辑表单（start/end 为北京时间 ISO 字符串） */
export interface DutyRosterPayload {
  project_id?: number | null;
  user_id?: number | null;
  shift?: string;
  duty_role?: string | null;
  start_time: string;
  end_time: string;
  note?: string | null;
}

export function getDutyMeta(): Promise<DutyMeta> {
  return http<DutyMeta>({ url: "/v1/duty/meta", method: "GET" });
}

export function listDutyRosters(params: DutyListParams): Promise<DutyRosterPage> {
  return http<DutyRosterPage>({ url: "/v1/duty/", method: "GET", params });
}

export function getOnDuty(project_id: number): Promise<OnDutyResult> {
  return http<OnDutyResult>({ url: "/v1/duty/on-duty", method: "GET", params: { project_id } });
}

export function getDutyRoster(id: number): Promise<DutyRoster> {
  return http<DutyRoster>({ url: `/v1/duty/${id}`, method: "GET" });
}

export function createDutyRoster(data: DutyRosterPayload): Promise<DutyRoster> {
  return http<DutyRoster>({ url: "/v1/duty/", method: "POST", data });
}

export function updateDutyRoster(id: number, data: Partial<DutyRosterPayload>): Promise<DutyRoster> {
  return http<DutyRoster>({ url: `/v1/duty/${id}`, method: "PUT", data });
}

export function deleteDutyRoster(id: number): Promise<{ deleted: boolean }> {
  return http<{ deleted: boolean }>({ url: `/v1/duty/${id}`, method: "DELETE" });
}

/** 批量删除值班排班 */
export function batchDeleteDutyRosters(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/duty/batch-delete", ids);
}
