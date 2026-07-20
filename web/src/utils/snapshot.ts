// 历史快照预览 / 导出相关的纯函数（与 PDF/Excel 导出同源数据）。
// 抽离到此便于单元测试，避免脆弱的组件级断言。
import type { SnapshotPreviewResult, SnapshotTypeCounts } from "@/api/alarm";
import { granularityLabel } from "@/utils/period";

/** 稀疏 by_type 兜底：仅含出现过的类型键，缺失按 0 计。 */
export function tc(
  obj: SnapshotTypeCounts | Record<string, number> | undefined,
  key: string,
): number {
  return (obj && (obj as Record<string, number>)[key]) || 0;
}

/** 占比小数 → 百分比文本（保留 1 位）。 */
export function pct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

/** 迷你趋势图的最大刻度（避免某周期 0 导致除零）。 */
export function snapTrendMaxOf(periods: { total: number }[]): number {
  return Math.max(1, ...periods.map((p) => p.total));
}

/**
 * 把快照预览结果拼成 TSV（可直接粘贴到 Excel）。
 * 顺序：标题/生成时间 → 概览 → 各周期分布 → 按项目汇总。
 * by_type 为稀疏字典（仅含出现的类型），缺失类型按 0 计。
 */
export function previewToTSV(p: SnapshotPreviewResult): string {
  const lines: string[] = [];
  lines.push(
    `历史快照预览（${granularityLabel((p.granularity as any) || "day")}）\t${p.meta.filters_desc}`,
  );
  lines.push(`生成时间\t${p.meta.generated_at}`);
  lines.push("");
  lines.push("【概览】");
  lines.push(`告警总数\t${p.summary.total}`);
  lines.push(`已处置\t${p.summary.handled}`);
  lines.push(`待处理\t${p.summary.pending}`);
  lines.push(`处置率\t${(p.summary.handle_rate * 100).toFixed(1)}%`);
  lines.push("");
  lines.push("【各周期告警分布】");
  lines.push("周期\t总数\t围栏侵入\t间距过近\t设备自报\t待处理\t已处置");
  for (const x of p.periods) {
    lines.push(
      [
        x.period,
        x.total,
        tc(x.by_type, "fence_intrusion"),
        tc(x.by_type, "distance_too_close"),
        tc(x.by_type, "device_alarm"),
        x.pending,
        x.handled,
      ].join("\t"),
    );
  }
  lines.push("");
  lines.push("【按项目汇总（跨整个窗口）】");
  lines.push("项目\t告警数\t占比\t围栏侵入\t间距过近\t设备自报\t待处理\t已处置");
  for (const x of p.project_summary) {
    lines.push(
      [
        x.project_name,
        x.count,
        pct(x.ratio),
        tc(x.by_type, "fence_intrusion"),
        tc(x.by_type, "distance_too_close"),
        tc(x.by_type, "device_alarm"),
        x.pending,
        x.handled,
      ].join("\t"),
    );
  }
  // 按项目明细（与 Excel 分 sheet / PDF 分节同源）
  for (const pd of p.projects_detail ?? []) {
    lines.push("");
    lines.push(
      `【按项目明细 · ${pd.project_name}（共 ${pd.count} 条${pd.capped ? "，已截断" : ""}）】`,
    );
    lines.push(
      "周期\tID\t告警时间\t类型\t级别\t设备类型\t设备编号\t设备名称\t关联围栏\t告警内容\t告警状态\t处置状态\t作业计划ID",
    );
    for (const r of pd.rows) {
      lines.push(
        [
          r.period,
          r.id,
          r.alarm_time,
          r.alarm_type,
          r.alarm_level,
          r.device_type,
          r.device_no,
          r.device_name,
          r.fence_name,
          r.alarm_info,
          r.alarm_status,
          r.handle_status,
          r.work_plan_id ?? "",
        ].join("\t"),
      );
    }
  }
  return lines.join("\n");
}
