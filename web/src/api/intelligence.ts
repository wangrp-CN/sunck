// 智能核心深化 (#④-1) 前端接口：风险预警阈值自学习标定 / 一键应用
// 与后端 app/api/v1/intelligence.py 对齐。
import { http } from "@/utils/request";

// 候选阈值 → 实际越阈率 扫描点
export interface ThresholdSweepPoint {
  threshold: number;
  breach_rate: number;
}

// 历史 risk_index 分布统计
export interface ThresholdStats {
  min: number;
  max: number;
  mean: number;
  median: number;
  p75: number;
  p90: number;
  p95: number;
}

// 一条标定记录（含诊断曲线）
export interface ThresholdCalibration {
  id: number;
  created_at: string | null;
  window_days: number;
  sample_count: number;
  target_breach_rate: number;
  current_threshold: number;
  recommended_threshold: number;
  method: string;
  min_threshold: number | null;
  max_threshold: number | null;
  actual_breach_rate: number | null;
  sweep: ThresholdSweepPoint[];
  stats: ThresholdStats;
}

// 标定接口返回（在记录基础上追加 calibration_id 与 message）
export interface CalibrateResult extends ThresholdCalibration {
  calibration_id: number;
  message: string;
}

export interface CalibrateParams {
  window_days?: number;
  target_breach_rate?: number;
  min_threshold?: number;
  max_threshold?: number;
}

export interface ApplyParams {
  threshold: number;
  source?: "auto" | "manual";
  calibration_id?: number | null;
}

// GET /threshold-calibration 返回
export interface ThresholdCalibrationView {
  active_threshold: number;
  latest: ThresholdCalibration | null;
}

// 查看当前生效阈值 + 最近一次标定
export function getThresholdCalibration(): Promise<ThresholdCalibrationView> {
  return http<ThresholdCalibrationView>({
    url: "/v1/intelligence/threshold-calibration",
    method: "GET",
  });
}

// 运行一次标定（超管），返回扫描曲线与推荐阈值
export function calibrateThreshold(params: CalibrateParams): Promise<CalibrateResult> {
  return http<CalibrateResult>({
    url: "/v1/intelligence/threshold-calibration/calibrate",
    method: "POST",
    data: {
      window_days: params.window_days ?? 90,
      target_breach_rate: params.target_breach_rate ?? 0.1,
      min_threshold: params.min_threshold ?? 40,
      max_threshold: params.max_threshold ?? 90,
    },
  });
}

// 一键应用生效阈值（超管）。auto=标定应用；manual=人工设定
export function applyThreshold(params: ApplyParams): Promise<{
  active_threshold: number;
  source: string;
}> {
  return http({
    url: "/v1/intelligence/threshold-calibration/apply",
    method: "POST",
    data: {
      threshold: params.threshold,
      source: params.source ?? "manual",
      calibration_id: params.calibration_id ?? null,
    },
  });
}
