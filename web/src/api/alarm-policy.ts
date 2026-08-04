// 告警策略 API 封装（🅱 M4 告警收敛/抑制/升级策略）
// 后端路由前缀 /v1/alarm-policies：
//   GET    /              分页列表（alarm_policy:list）
//   GET    /meta          枚举选项（alarm_policy:list）
//   POST   /run-escalations 手动触发一轮超时升级扫描（alarm_policy:manage）
//   GET    /{id}          详情（alarm_policy:list）
//   POST   /              新增（alarm_policy:manage）
//   PUT    /{id}          编辑（alarm_policy:manage）
//   DELETE /{id}          删除（逻辑，alarm_policy:manage）
// 约定：http<T> 已解包 data，失败时抛 Error(message)。
import { http } from "@/utils/request";
import { batchDelete, type BatchDeleteResult } from "@/api/batch";

/** 单条策略（与后端 AlarmPolicyOut 对齐） */
export interface AlarmPolicy {
  id: number;
  name: string;
  project_id: number | null;
  project_name: string | null;
  alarm_type: string | null;
  enabled: boolean;
  suppress_window_seconds: number | null;
  silence_start: string | null;
  silence_end: string | null;
  escalate_after_minutes: number | null;
  escalate_to_level: string;
  escalate_channels: string;
  note: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 分页列表 */
export interface AlarmPolicyPage {
  total: number;
  items: AlarmPolicy[];
  page: number;
  size: number;
}

/** 枚举元数据 */
export interface AlarmPolicyMeta {
  alarm_types: { key: string; label: string }[];
  levels: string[];
  channels: string[];
}

/** 升级扫描结果 */
export interface EscalationResult {
  scanned: number;
  escalated: number;
  alarm_ids: number[];
}

/** 列表查询参数 */
export interface AlarmPolicyListParams {
  project_id?: number;
  alarm_type?: string;
  enabled?: boolean;
  page?: number;
  size?: number;
}

/** 新建/编辑表单（project_id 为空=全局；alarm_type 为空=通配；
 *  silence 空串=清除静默时段；suppress/escalate 0 或空=清除/关闭） */
export interface AlarmPolicyPayload {
  name: string;
  project_id?: number | null;
  alarm_type?: string | null;
  enabled?: boolean;
  suppress_window_seconds?: number | null;
  silence_start?: string | null;
  silence_end?: string | null;
  escalate_after_minutes?: number | null;
  escalate_to_level?: string;
  escalate_channels?: string;
  note?: string | null;
}

export function getAlarmPolicyMeta(): Promise<AlarmPolicyMeta> {
  return http<AlarmPolicyMeta>({ url: "/v1/alarm-policies/meta", method: "GET" });
}

export function listAlarmPolicies(params: AlarmPolicyListParams): Promise<AlarmPolicyPage> {
  return http<AlarmPolicyPage>({ url: "/v1/alarm-policies/", method: "GET", params });
}

export function getAlarmPolicy(id: number): Promise<AlarmPolicy> {
  return http<AlarmPolicy>({ url: `/v1/alarm-policies/${id}`, method: "GET" });
}

export function createAlarmPolicy(data: AlarmPolicyPayload): Promise<AlarmPolicy> {
  return http<AlarmPolicy>({ url: "/v1/alarm-policies/", method: "POST", data });
}

export function updateAlarmPolicy(id: number, data: Partial<AlarmPolicyPayload>): Promise<AlarmPolicy> {
  return http<AlarmPolicy>({ url: `/v1/alarm-policies/${id}`, method: "PUT", data });
}

export function deleteAlarmPolicy(id: number): Promise<{ deleted: boolean }> {
  return http<{ deleted: boolean }>({ url: `/v1/alarm-policies/${id}`, method: "DELETE" });
}

export function runEscalations(): Promise<EscalationResult> {
  return http<EscalationResult>({ url: "/v1/alarm-policies/run-escalations", method: "POST" });
}

/** 批量删除告警策略 */
export function batchDeleteAlarmPolicies(ids: number[]): Promise<BatchDeleteResult> {
  return batchDelete("/v1/alarm-policies/batch-delete", ids);
}
