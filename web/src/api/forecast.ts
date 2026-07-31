// 风险预测（Phase 5 智能化预测）前端接口
// 与后端 app/api/v1/forecasts.py 对齐：
// - GET  /v1/forecasts          预测列表（scope_type/metric/project_id 过滤）
// - GET  /v1/forecasts/preview  单对象序列预览（历史点+拟合+预测点+置信带）
// - POST /v1/forecasts/recompute 重算
import { http } from "@/utils/request";

// forecast 表一行（列表项）
export interface ForecastItem {
  id: number;
  project_id: number | null;
  scope_type: "project" | "device";
  ref_id: string;
  name: string | null;
  metric: "risk_index" | "health_score";
  horizon_days: number;
  sample_count: number;
  last_value: number;
  slope: number;
  intercept: number;
  forecast_value: number;
  forecast_level: string | null; // risk: 高/中/低；health: 优/良/中/差
  std_resid: number | null;
  forecast_lower: number | null;
  forecast_upper: number | null;
  forecast_at: string;
  computed_at: string;
}

// preview 的历史序列点
export interface ForecastSeriesPoint {
  at: string;
  value: number;
}

// preview 的拟合结果（样本不足时为 null）
export interface ForecastFit {
  metric: string;
  horizon_days: number;
  sample_count: number;
  last_value: number;
  slope: number;
  intercept: number;
  forecast_value: number;
  forecast_level: string | null;
  std_resid: number;
  forecast_lower: number;
  forecast_upper: number;
  forecast_at: string;
  computed_at: string;
}

export interface ForecastPreview {
  scope_type: string;
  ref_id: string;
  metric: string;
  horizon_days: number;
  series: ForecastSeriesPoint[];
  forecast: ForecastFit | null;
}

export interface ListForecastParams {
  project_id?: number;
  scope_type?: "project" | "device";
  metric?: "risk_index" | "health_score";
}

export function listForecasts(params: ListForecastParams = {}): Promise<{ items: ForecastItem[] }> {
  return http<{ items: ForecastItem[] }>({ url: "/v1/forecasts/", method: "GET", params });
}

export function previewForecast(params: {
  ref_id: string;
  scope_type: "project" | "device";
  horizon_days?: number;
  history_days?: number;
}): Promise<ForecastPreview> {
  return http<ForecastPreview>({ url: "/v1/forecasts/preview", method: "GET", params });
}

export function recomputeForecasts(params: { project_id?: number; horizon_days?: number } = {}): Promise<
  ForecastItem | { computed: number; skipped: number; projects: number; devices: number }
> {
  return http({ url: "/v1/forecasts/recompute", method: "POST", params });
}

// 预测命中率报表结果（预测性预警闭环验证）
export interface PredictionHitRate {
  verifiable: number;
  hits: number;
  false_positives: number;
  pending: number;
  hit_rate: number | null;
  avg_lead_hours: number | null;
  by_metric: Record<string, { metric: string; verifiable: number; hits: number; false_positives: number; pending: number; hit_rate: number | null }>;
  by_project: { project_id: number; verifiable: number; hits: number; false_positives: number; pending: number; hit_rate: number | null }[];
  period_days: number;
  generated_at: string;
}

export function getForecastHitRate(params: {
  days?: number;
  project_id?: number;
  metric?: "risk_index" | "health_score";
} = {}): Promise<PredictionHitRate> {
  return http<PredictionHitRate>({ url: "/v1/forecasts/hit-rate", method: "GET", params });
}

// 回测摘要（POST /v1/forecasts/backtest 返回）
export interface BacktestSummary {
  models: string[];
  anchors: number;
  rows: number;
  by_model: Record<string, { rows: number; hits: number; false_positives: number }>;
  horizon_days: number;
}

export function runForecastBacktest(params: {
  days?: number;
  horizon_days?: number;
} = {}): Promise<BacktestSummary> {
  return http<BacktestSummary>({ url: "/v1/forecasts/backtest", method: "POST", params });
}

// A/B 命中率报表（GET /v1/forecasts/hit-rate/ab 返回）
export interface ABModelRow {
  model_version: string;
  label: string;
  verifiable: number;
  hits: number;
  false_positives: number;
  pending: number;
  hit_rate: number | null;
  false_positive_rate: number | null;
  avg_lead_hours: number | null;
  by_metric: Record<
    string,
    {
      metric: string;
      verifiable: number;
      hits: number;
      false_positives: number;
      pending: number;
      hit_rate: number | null;
    }
  >;
}

export interface ABComparison {
  baseline: string;
  baseline_label: string;
  challenger: string;
  challenger_label: string;
  hit_rate_baseline: number | null;
  hit_rate_challenger: number | null;
  hit_rate_delta: number | null;
  hit_rate_delta_pct: number | null;
  false_positive_rate_baseline: number | null;
  false_positive_rate_challenger: number | null;
  false_positive_rate_delta: number | null;
  avg_lead_hours_baseline: number | null;
  avg_lead_hours_challenger: number | null;
  lead_delta_hours: number | null;
  better: boolean;
  summary: string;
}

export interface ABHitRate {
  period_days: number;
  generated_at: string;
  models: ABModelRow[];
  comparison: ABComparison | null;
}

export function getForecastABHitRate(params: {
  days?: number;
  project_id?: number;
  metric?: "risk_index" | "health_score";
} = {}): Promise<ABHitRate> {
  return http<ABHitRate>({ url: "/v1/forecasts/hit-rate/ab", method: "GET", params });
}

// 当前上线默认预测模型（GET /v1/forecasts/model/default 返回）
export interface ForecastDefaultModel {
  model_version: string;
  available: { model_version: string; label: string }[];
}

export function getForecastDefaultModel(): Promise<ForecastDefaultModel> {
  return http<ForecastDefaultModel>({ url: "/v1/forecasts/model/default", method: "GET" });
}

export function setForecastDefaultModel(model_version: string): Promise<{
  model_version: string;
  label: string;
  recomputed: unknown;
  predictive_alerts: unknown;
}> {
  return http({
    url: "/v1/forecasts/model/default",
    method: "POST",
    data: { model_version },
  });
}
