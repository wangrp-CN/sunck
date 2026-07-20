import { describe, expect, it } from "vitest";
import { pct, previewToTSV, snapTrendMaxOf, tc } from "@/utils/snapshot";
import type { SnapshotPreviewResult } from "@/api/alarm";

// 构造一份含「稀疏 by_type」（某周期缺 distance_too_close 键）的快照
const fixture: SnapshotPreviewResult = {
  granularity: "month",
  period_keys: ["2026-05", "2026-06"],
  meta: {
    title: "告警历史快照",
    generated_at: "2026-07-17 10:30:00",
    filters_desc: "全部项目",
  },
  summary: {
    total: 648,
    handled: 206,
    pending: 442,
    handle_rate: 0.318,
    by_type: { fence_intrusion: 100, distance_too_close: 50, device_alarm: 498 },
    by_level: { 严重: 10, 警告: 20, 提示: 618 },
    by_handle_status: { 待处理: 442, 已处置: 206 },
  },
  periods: [
    {
      period: "2026-05",
      total: 109,
      // 故意缺失 distance_too_close → 稀疏字典
      by_type: { fence_intrusion: 40, device_alarm: 69 } as any,
      by_level: { 严重: 1, 提示: 108 },
      pending: 80,
      handled: 29,
      by_project: [],
    },
    {
      period: "2026-06",
      total: 106,
      by_type: { fence_intrusion: 30, distance_too_close: 26, device_alarm: 50 },
      by_level: { 严重: 2, 警告: 4, 提示: 100 },
      pending: 90,
      handled: 16,
      by_project: [],
    },
  ],
  project_summary: [
    {
      project_name: "示例项目A",
      count: 200,
      ratio: 0.3086,
      by_type: { fence_intrusion: 70, distance_too_close: 26, device_alarm: 104 },
      pending: 170,
      handled: 30,
    },
  ],
};

describe("utils/snapshot.ts", () => {
  it("tc 对稀疏 by_type 兜底为 0", () => {
    const bt = { fence_intrusion: 5 };
    expect(tc(bt, "fence_intrusion")).toBe(5);
    expect(tc(bt, "distance_too_close")).toBe(0); // 缺失键
    expect(tc(undefined, "device_alarm")).toBe(0); // 整体缺失
    expect(tc({}, "device_alarm")).toBe(0);
  });

  it("pct 保留 1 位小数", () => {
    expect(pct(0.318)).toBe("31.8%");
    expect(pct(0)).toBe("0.0%");
    expect(pct(1)).toBe("100.0%");
  });

  it("snapTrendMaxOf 取最大值且空数组返回 1（防除零）", () => {
    expect(snapTrendMaxOf([])).toBe(1);
    expect(snapTrendMaxOf([{ total: 3 }, { total: 9 }, { total: 5 }])).toBe(9);
    expect(snapTrendMaxOf([{ total: 0 }])).toBe(1);
  });

  it("previewToTSV 含三段标题与概览指标", () => {
    const tsv = previewToTSV(fixture);
    expect(tsv).toContain("历史快照预览（当月）\t全部项目");
    expect(tsv).toContain("生成时间\t2026-07-17 10:30:00");
    expect(tsv).toContain("【概览】");
    expect(tsv).toContain("告警总数\t648");
    expect(tsv).toContain("处置率\t31.8%");
    expect(tsv).toContain("【各周期告警分布】");
    expect(tsv).toContain("【按项目汇总（跨整个窗口）】");
  });

  it("previewToTSV 周期行按 Tab 分隔且稀疏类型补 0", () => {
    const tsv = previewToTSV(fixture);
    const lines = tsv.split("\n");
    const headerIdx = lines.findIndex((l) => l.startsWith("周期\t总数"));
    expect(headerIdx).toBeGreaterThan(0);
    const row0 = lines[headerIdx + 1]; // 2026-05
    // 周期\t总数\t围栏侵入\t间距过近\t设备自报\t待处理\t已处置
    expect(row0).toBe("2026-05\t109\t40\t0\t69\t80\t29");
    const row1 = lines[headerIdx + 2]; // 2026-06
    expect(row1).toBe("2026-06\t106\t30\t26\t50\t90\t16");
  });

  it("previewToTSV 项目汇总行含占比与分类型计数", () => {
    const tsv = previewToTSV(fixture);
    const lines = tsv.split("\n");
    const headerIdx = lines.findIndex((l) => l.startsWith("项目\t告警数"));
    const row = lines[headerIdx + 1];
    // 项目\t告警数\t占比\t围栏侵入\t间距过近\t设备自报\t待处理\t已处置
    expect(row).toBe("示例项目A\t200\t30.9%\t70\t26\t104\t170\t30");
  });

  it("previewToTSV 对相同输入稳定可重现", () => {
    expect(previewToTSV(fixture)).toBe(previewToTSV(structuredClone(fixture)));
  });
});
