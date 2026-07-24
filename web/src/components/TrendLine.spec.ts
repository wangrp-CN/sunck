import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import TrendLine from "@/components/TrendLine.vue";

type TPoint = { t: string; v: number };

const series: TPoint[] = [
  { t: "2026-06-25T02:30:00", v: 20 },
  { t: "2026-06-26T02:30:00", v: 35 },
  { t: "2026-06-27T02:30:00", v: 28 },
  { t: "2026-06-28T02:30:00", v: 62 },
];

describe("components/TrendLine.vue", () => {
  it("renders an svg with one line path when data is present", () => {
    const wrapper = mount(TrendLine, { props: { points: series, width: 140 } });
    expect(wrapper.find("svg").exists()).toBe(true);
    // 折线路径存在且以 M 开头、包含 L 段
    const path = wrapper.find("path.line");
    expect(path.exists()).toBe(true);
    expect(path.attributes("d")!.startsWith("M")).toBe(true);
    expect(path.attributes("d")!.includes("L")).toBe(true);
  });

  it("renders an area path when showArea is true", () => {
    const wrapper = mount(TrendLine, { props: { points: series, showArea: true } });
    // 面积路径以 M 开头并以 Z 闭合
    const area = wrapper.findAll("path").find((p) => p.attributes("d")?.endsWith("Z"));
    expect(area).toBeTruthy();
  });

  it("draws a dashed threshold line and a last-point marker", () => {
    const wrapper = mount(TrendLine, {
      props: { points: series, threshold: 60, width: 140, height: 40 },
    });
    expect(wrapper.find("line.threshold").exists()).toBe(true);
    expect(wrapper.find("circle.last-dot").exists()).toBe(true);
  });

  it("shows a placeholder when there is no data", () => {
    const wrapper = mount(TrendLine, { props: { points: [] } });
    expect(wrapper.find("svg").exists()).toBe(false);
    expect(wrapper.find(".tl-empty").exists()).toBe(true);
    expect(wrapper.text()).toContain("—");
  });

  it("scales y to include the threshold even when data is below it", () => {
    const below: TPoint[] = [
      { t: "2026-06-25T02:30:00", v: 10 },
      { t: "2026-06-26T02:30:00", v: 15 },
    ];
    const wrapper = mount(TrendLine, {
      props: { points: below, threshold: 60, width: 140, height: 40 },
    });
    const th = wrapper.find("line.threshold");
    // 阈值线应位于绘图区顶部（y 较小），而非越界
    const y = Number(th.attributes("y1"));
    expect(y).toBeGreaterThanOrEqual(6);
    expect(y).toBeLessThan(40);
  });
});
