import request, { http } from "@/utils/request";

// 风险健康报表（Phase 1 报表导出）：基于 risk_health_snapshot 聚合的日报/周报预览与导出。

export type RiskHealthPeriod = "daily" | "weekly";

export interface RiskHealthReportSummary {
  project_count: number;
  avg_risk: number | null;
  high_risk_count: number;
  device_count: number;
  avg_health: number | null;
  offline_count: number;
  health_dist: { 优: number; 良: number; 中: number; 差: number };
  online_dist: { fresh: number; stale: number; offline: number };
}

export interface RiskHealthReportProjectRow {
  project_id: number;
  name: string;
  risk_index: number | null;
  risk_level: string | null;
  prev_risk_index: number | null;
  delta: number | null;
}

export interface RiskHealthReportDeviceRow {
  device_no: string;
  name: string;
  health_score: number | null;
  health_level: string | null;
  online_state: string | null;
}

export interface RiskHealthReportPreview {
  period_type: RiskHealthPeriod;
  period_label: string;
  range_start: string;
  range_end: string;
  summary: RiskHealthReportSummary;
  project_rows: RiskHealthReportProjectRow[];
  device_rows: RiskHealthReportDeviceRow[];
  top_risky_projects: RiskHealthReportProjectRow[];
  top_unhealthy_devices: RiskHealthReportDeviceRow[];
}

// 风险健康报表预览（JSON）
export function getRiskHealthReportPreview(params: {
  period_type: RiskHealthPeriod;
}): Promise<RiskHealthReportPreview> {
  return http<RiskHealthReportPreview>({
    url: "/v1/reports/risk-health/preview",
    method: "GET",
    params,
  });
}

// 导出风险健康报表（excel|pdf）——返回二进制 Blob，不走 http<T> 解包
export function exportRiskHealthReport(
  fmt: "excel" | "pdf",
  params: { period_type: RiskHealthPeriod },
): Promise<Blob> {
  return request
    .get("/v1/reports/risk-health/export", {
      params: { fmt, period_type: params.period_type },
      responseType: "blob",
    })
    .then((r) => r.data as Blob);
}
