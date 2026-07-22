// 告警管理 API 封装（处置 + 配置 + 报表/导出）；列表复用 @/api/realtime 的 fetchAlarms
import request, { http } from "@/utils/request";
import type { Alarm, AlarmConfig, AlarmHandleRequest } from "@/types";

// 处置告警（处理/忽略/确认/已消警）
export function handleAlarm(
  id: number,
  req: AlarmHandleRequest,
): Promise<Alarm> {
  return http<Alarm>({
    url: `/v1/alarms/${id}/handle`,
    method: "POST",
    data: req,
  });
}

// 批量处置告警：超出当前用户数据范围者自动跳过，返回 handled/skipped/results
export interface AlarmBatchHandleRequest {
  ids: number[];
  handle_status: string;
  content?: string | null;
}
export interface AlarmBatchHandleResult {
  handled: number;
  skipped: number;
  results: { id: number; success: boolean; message?: string }[];
}
export function batchHandleAlarms(
  req: AlarmBatchHandleRequest,
): Promise<AlarmBatchHandleResult> {
  return http<AlarmBatchHandleResult>({
    url: `/v1/alarms/batch-handle`,
    method: "POST",
    data: req,
  });
}

// 获取告警配置
export function getAlarmConfig(): Promise<AlarmConfig> {
  return http<AlarmConfig>({
    url: "/v1/alarms/config",
    method: "GET",
  });
}

// 更新告警配置
export function updateAlarmConfig(
  req: Partial<AlarmConfig>,
): Promise<AlarmConfig> {
  return http<AlarmConfig>({
    url: "/v1/alarms/config",
    method: "PUT",
    data: req,
  });
}

// ---- 报表 / 导出 ----

// 聚合粒度：天 / 周 / 月（趋势图按粒度切换）
export type Granularity = "day" | "week" | "month";

// 报表查询参数（均可选；时间为 ISO 字符串）
export interface AlarmReportParams {
  start?: string;
  end?: string;
  project_id?: number;
  alarm_type?: string;
  handle_status?: string;
  alarm_level?: string;
  granularity?: Granularity;
}

// 报表聚合结果
export interface AlarmReportDayPoint {
  date?: string;
  period?: string;
  count: number;
  by_type?: Record<string, number>;
  by_level?: Record<string, number>;
}

export interface AlarmReportSummary {
  total: number;
  handled: number;
  pending: number;
  handle_rate: number;
  by_type: Record<string, number>;
  by_level: Record<string, number>;
  by_handle_status: Record<string, number>;
  by_day: AlarmReportDayPoint[];
  by_period: AlarmReportDayPoint[];
}

export interface AlarmReportResult {
  summary: AlarmReportSummary;
  items: Alarm[];
  preview_count: number;
  filters_desc: string;
}

// 查询告警报表（聚合 + 明细预览）
export function fetchAlarmReport(
  params: AlarmReportParams,
): Promise<AlarmReportResult> {
  return http<AlarmReportResult>({
    url: "/v1/alarms/report",
    method: "GET",
    params,
  });
}

// 仅取聚合统计（summary_only=true）用于主视图「随筛选联动」的轻量趋势刷新
export function fetchAlarmTrend(
  params: AlarmReportParams,
): Promise<{ summary: AlarmReportSummary; filters_desc: string }> {
  return http<{ summary: AlarmReportSummary; filters_desc: string }>({
    url: "/v1/alarms/report",
    method: "GET",
    params: { ...params, summary_only: true },
  });
}

// 下钻：按周期(天/周/月)告警明细（柱状图点击某周期）
export interface AlarmPeriodParams extends AlarmReportParams {
  granularity: Granularity;
  period: string; // day=YYYY-MM-DD / week=YYYY-Www / month=YYYY-MM
}
export interface AlarmPeriodResult {
  granularity: Granularity;
  period: string;
  total: number;
  items: Alarm[];
  filters_desc: string;
}
export function fetchAlarmPeriod(
  params: AlarmPeriodParams,
): Promise<AlarmPeriodResult> {
  return http<AlarmPeriodResult>({
    url: "/v1/alarms/period",
    method: "GET",
    params,
  });
}

// 导出参数：报表筛选 + 可选周期联动（period 提供时后端按整周/整月导出）
export interface AlarmExportParams extends AlarmReportParams {
  period?: string; // 与 granularity 搭配：week=YYYY-Www / month=YYYY-MM / day=YYYY-MM-DD
  snapshot?: boolean; // 历史快照：按 granularity 把 [start,end] 拆成多个周期，每个周期单独成表
}

// 导出告警报表（excel|pdf）——返回二进制 Blob，不走 http<T> 解包
export async function exportAlarmReport(
  fmt: "excel" | "pdf",
  params: AlarmExportParams,
): Promise<Blob> {
  const resp = await request.get("/v1/alarms/export", {
    params: { ...params, fmt },
    responseType: "blob",
  });
  return resp.data as Blob;
}

// ---- 快照预览（JSON，与 Excel/PDF 快照同源）----

export interface SnapshotTypeCounts {
  fence_intrusion: number;
  distance_too_close: number;
  device_alarm: number;
}
export interface SnapshotProjectBreakdown {
  project_name: string;
  count: number;
  by_level: Record<string, number>;
}
export interface SnapshotPeriod {
  period: string;
  total: number;
  by_type: SnapshotTypeCounts;
  by_level: Record<string, number>;
  pending: number;
  handled: number;
  by_project: SnapshotProjectBreakdown[];
}
export interface SnapshotProjectSummary {
  project_name: string;
  count: number;
  ratio: number;
  by_type: SnapshotTypeCounts;
  pending: number;
  handled: number;
}
export interface SnapshotProjectDetailRow {
  period: string;
  id: number | string;
  alarm_time: string;
  alarm_type: string;
  alarm_level: string;
  device_type: string;
  device_no: string;
  device_name: string;
  fence_name: string;
  alarm_info: string;
  alarm_status: string;
  handle_status: string;
  work_plan_id: number | string | null;
}
export interface SnapshotProjectDetail {
  project_name: string;
  count: number;
  capped: boolean;
  rows: SnapshotProjectDetailRow[];
}
export interface SnapshotSummary {
  total: number;
  handled: number;
  pending: number;
  handle_rate: number;
  by_type: Record<string, number>;
  by_level: Record<string, number>;
  by_handle_status: Record<string, number>;
}
export interface SnapshotPreviewMeta {
  title: string;
  generated_at: string;
  filters_desc: string;
}
export interface SnapshotPreviewResult {
  granularity: string;
  period_keys: string[];
  meta: SnapshotPreviewMeta;
  summary: SnapshotSummary;
  periods: SnapshotPeriod[];
  project_summary: SnapshotProjectSummary[];
  projects_detail?: SnapshotProjectDetail[];
}

// 查询历史快照预览（概览 + 各周期分布 + 按项目汇总），渲染后再决定是否导出
export function fetchSnapshotPreview(params: {
  granularity?: Granularity;
  start?: string;
  end?: string;
  project_id?: number;
  alarm_type?: string;
  handle_status?: string;
  alarm_level?: string;
}): Promise<SnapshotPreviewResult> {
  return http<SnapshotPreviewResult>({
    url: "/v1/alarms/snapshot/preview",
    method: "GET",
    params,
  });
}
