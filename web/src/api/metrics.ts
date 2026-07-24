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
