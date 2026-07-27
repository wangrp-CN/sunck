/**
 * 趋势异常检测（统计基线法）。
 *
 * 给定一条单变量时间序列（按时间旧→新），对每一点用其**之前的滚动窗口**
 * （默认 7 个周期，不含当前点）估计基线均值/标准差，计算 z-score：
 *   z = (value - mean) / std
 * 当 |z| > k（默认 2.0，即偏离基线超过 2 个标准差）时标记为异常，方向按 z 符号
 * 判为 spike（突增）/ drop（突降）。
 *
 * 设计要点：
 * - 基线只用「历史」不含当前点，避免自污染（用未来或自身会掩盖异常）。
 * - 历史样本不足 minTrailing（默认 3）时该点不判异常（无法建立可靠基线）。
 * - 序列整体短于 minPoints（默认 5）时整条不判异常（防止 2~3 点的误报）。
 * - 零依赖、纯函数、可在前端直接对已有序列计算（与后端 /v1/dashboard/stats
 *   返回的 device_trend_period / alarm_trend_period 等同源同桶口径）。
 */

export type AnomalyDirection = "spike" | "drop" | null;

export interface AnomalyPoint {
  value: number;
  baselineMean: number;
  baselineStd: number;
  z: number;
  isAnomaly: boolean;
  direction: AnomalyDirection;
}

export interface DetectOptions {
  /** 滚动基线窗口（不含当前点） */
  window?: number;
  /** z-score 阈值，超过即异常 */
  k?: number;
  /** 单点判异常所需的最少历史样本数 */
  minTrailing?: number;
  /** 序列最短长度，低于此整条不判异常 */
  minPoints?: number;
}

const DEFAULTS = { window: 7, k: 2.0, minTrailing: 3, minPoints: 5 };

export function detectAnomalies(
  values: number[],
  opts: DetectOptions = {},
): AnomalyPoint[] {
  const window = opts.window ?? DEFAULTS.window;
  const k = opts.k ?? DEFAULTS.k;
  const minTrailing = opts.minTrailing ?? DEFAULTS.minTrailing;
  const minPoints = opts.minPoints ?? DEFAULTS.minPoints;

  const n = values.length;
  const out: AnomalyPoint[] = [];

  // 序列太短：直接返回非异常（保留 value 便于调用方对齐索引）
  if (n < minPoints) {
    return values.map((v) => ({
      value: v,
      baselineMean: v,
      baselineStd: 0,
      z: 0,
      isAnomaly: false,
      direction: null,
    }));
  }

  for (let i = 0; i < n; i++) {
    const start = Math.max(0, i - window);
    const prev = values.slice(start, i); // 不含当前点
    const v = values[i];

    if (prev.length < minTrailing) {
      out.push({
        value: v,
        baselineMean: v,
        baselineStd: 0,
        z: 0,
        isAnomaly: false,
        direction: null,
      });
      continue;
    }

    const mean = prev.reduce((a, b) => a + b, 0) / prev.length;
    const variance =
      prev.reduce((a, b) => a + (b - mean) ** 2, 0) / prev.length;
    const std = Math.sqrt(variance);

    let z = 0;
    let isAnomaly = false;
    let direction: AnomalyDirection = null;

    if (std > 1e-9) {
      z = (v - mean) / std;
      isAnomaly = Math.abs(z) > k;
      direction = !isAnomaly ? null : z > 0 ? "spike" : "drop";
    } else {
      // 基线恒定（std≈0）：任何偏离常量的值都视为异常，
      // 避免「长期平稳后突跳」因分母为 0 而被漏检。
      const dev = Math.abs(v - mean);
      if (dev > 1e-9) {
        isAnomaly = true;
        direction = v > mean ? "spike" : "drop";
        z = (v > mean ? 1 : -1) * Infinity;
      }
    }

    out.push({
      value: v,
      baselineMean: mean,
      baselineStd: std,
      z,
      isAnomaly,
      direction,
    });
  }

  return out;
}
