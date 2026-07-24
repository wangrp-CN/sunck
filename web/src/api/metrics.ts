import { http } from "@/utils/request";

// 智能核心 v2：风险/健康时序趋势与阈值预警前端接口。
// 与后端 app/api/v1/metrics.py 对齐：risk-trend / health-trend / risk-alerts。

export interface RiskTrendPoint {
  snapshot_at: string;
  risk_index: number;
  risk_level: string | null;
}

export interface RiskTrendResp {
  project_id: number;
  days: number;
  series: RiskTrendPoint[];
}

export interface HealthTrendPoint {
  snapshot_at: string;
  health_score: number;
  health_level: string | null;
  online_state: string | null;
}

export interface HealthTrendResp {
  device_no: string;
  days: number;
  series: HealthTrendPoint[];
}

export interface RiskAlertItem {
  project_id: number;
  project_name: string;
  risk_index: number;
  risk_level: string | null;
  raw_score: number | null;
  is_new: boolean;
  breached_at: string | null;
}

export interface RiskAlertsResp {
  total: number;
  items: RiskAlertItem[];
}

// 风险预警阈值（与后端 app/config.py 的 risk_alert_threshold 默认 60 对齐）。
// 若运维调高/调低该值，前端这里需同步；后续可经配置接口下发。
export const RISK_ALERT_THRESHOLD = 60;

// 项目风险指数时间序列（受数据范围约束）
export function getRiskTrend(projectId: number, days = 30): Promise<RiskTrendResp> {
  return http<RiskTrendResp>({
    url: "/v1/metrics/risk-trend",
    method: "GET",
    params: { project_id: projectId, days },
  });
}

// 单设备健康分时间序列
export function getHealthTrend(deviceNo: string, days = 30): Promise<HealthTrendResp> {
  return http<HealthTrendResp>({
    url: "/v1/metrics/health-trend",
    method: "GET",
    params: { device_no: deviceNo, days },
  });
}

// 当前越阈项目列表（受数据范围约束，含 is_new 上升沿标记）
export function getRiskAlerts(): Promise<RiskAlertsResp> {
  return http<RiskAlertsResp>({
    url: "/v1/metrics/risk-alerts",
    method: "GET",
  });
}

// ---------------------------------------------------------------------------
// 跨设备根因关联（#77）
// ---------------------------------------------------------------------------

export interface CorrelationItem {
  id: number;
  project_id: number | null;
  project_name: string | null;
  spatial_type: "fence" | "geo" | "device";
  scope_key: string;
  fence_name: string | null;
  grid_cell: string | null;
  started_at: string | null;
  ended_at: string | null;
  alarm_count: number;
  device_count: number;
  is_cross_device: boolean;
  max_level: string | null;
  device_nos: string[];
  levels: string[];
  alarm_types: string[];
  alarm_ids: number[];
  root_cause_hint: string | null;
  computed_at: string | null;
}

export interface CorrelationsResp {
  total: number;
  items: CorrelationItem[];
}

export interface CorrelationMember {
  id: number;
  device_no: string | null;
  device_name: string | null;
  alarm_type: string | null;
  alarm_level: string | null;
  alarm_status: string | null;
  handle_status: string | null;
  alarm_time: string | null;
  alarm_info: string | null;
  fence_name: string | null;
  project_id: number | null;
}

export interface CorrelationMembersResp {
  group_id: number;
  total: number;
  items: CorrelationMember[];
}

// 当前跨设备根因关联事件组（受数据范围约束）
export function getCorrelations(onlyCrossDevice = false, limit = 100): Promise<CorrelationsResp> {
  return http<CorrelationsResp>({
    url: "/v1/metrics/correlations",
    method: "GET",
    params: { only_cross_device: onlyCrossDevice, limit },
  });
}

// 某事件组的成员告警明细（受数据范围约束），供展开行查看
export function getCorrelationMembers(groupId: number): Promise<CorrelationMembersResp> {
  return http<CorrelationMembersResp>({
    url: `/v1/metrics/correlations/${groupId}/members`,
    method: "GET",
  });
}

// 手动触发一次关联计算（仅超级管理员）
export function runCorrelations(windowHours = 24, gapMinutes = 30): Promise<{
  groups: number;
  cross_device_groups: number;
  window_hours: number;
  gap_minutes: number;
  computed_at: string;
}> {
  return http({
    url: "/v1/metrics/correlations/run",
    method: "POST",
    params: { window_hours: windowHours, gap_minutes: gapMinutes },
  });
}

// 跨设备关联汇总（受数据范围约束），大屏「今日新增跨设备共因」卡片用
export interface CorrelationSummaryResp {
  total: number;
  cross_device_total: number;
  today_cross_device: number;
  today_projects: number;
  by_level: Record<string, number>;
}

// 关联事件组每日计数趋势（sparkline 用）
export interface CorrelationTrendPoint {
  date: string; // YYYY-MM-DD
  count: number;
}

export interface CorrelationTrendResp {
  days: number;
  only_cross_device: boolean;
  series: CorrelationTrendPoint[];
}

// 跨设备关联汇总
export function getCorrelationSummary(): Promise<CorrelationSummaryResp> {
  return http<CorrelationSummaryResp>({
    url: "/v1/metrics/correlations/summary",
    method: "GET",
  });
}

// 关联事件组每日计数趋势（按事件窗 started_at 分桶）
export function getCorrelationTrend(
  days = 30,
  onlyCrossDevice = false,
): Promise<CorrelationTrendResp> {
  return http<CorrelationTrendResp>({
    url: "/v1/metrics/correlations/trend",
    method: "GET",
    params: { days, only_cross_device: onlyCrossDevice },
  });
}
