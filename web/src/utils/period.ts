// 周期标签与格式化工具（趋势图按天/周/月聚合时用）。

import type { Granularity } from "@/api/alarm";

/**
 * 把后端返回的周期 key 格式化为图表 X 轴短标签。
 * - day:   "2026-07-16" → "07-16"
 * - week:  "2026-W29"   → "W29"
 * - month: "2026-07"    → "2026-07"
 */
export function formatPeriodLabel(period: string, granularity: Granularity): string {
  if (!period) return "";
  if (granularity === "week") {
    const m = period.match(/(\d{4})-W(\d{1,2})/);
    if (m) return `W${parseInt(m[2], 10)}`;
    return period;
  }
  if (granularity === "month") {
    return period;
  }
  // day：YYYY-MM-DD → MM-DD
  const p = period.split("-");
  return p.length === 3 ? `${p[1]}-${p[2]}` : period;
}

/** 粒度中文名（下钻弹窗标题等用）。 */
export function granularityLabel(g: Granularity): string {
  return g === "week" ? "当周" : g === "month" ? "当月" : "当日";
}
