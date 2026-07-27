import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import CorrelationHeatmap from "@/components/CorrelationHeatmap.vue";
import type { CorrelationHeatPoint } from "@/api/metrics";

function pt(over: Partial<CorrelationHeatPoint>): CorrelationHeatPoint {
  return {
    id: 1,
    project_id: 1,
    project_name: "项目A",
    spatial_type: "geo",
    fence_name: null,
    grid_cell: "3990,11640",
    lng: 116.4,
    lat: 39.9,
    gcj02: { lng: 116.406, lat: 39.901 },
    weight: 3,
    alarm_count: 3,
    device_count: 2,
    max_level: "警告",
    is_cross_device: true,
    root_cause_hint: "同网格多设备短时集中告警",
    ...over,
  };
}

const points: CorrelationHeatPoint[] = [
  pt({ id: 1, lng: 116.4, lat: 39.9, weight: 2, alarm_count: 2 }),
  pt({ id: 2, lng: 116.5, lat: 40.0, weight: 8, alarm_count: 8, max_level: "严重" }),
  pt({
    id: 3,
    spatial_type: "fence",
    grid_cell: null,
    fence_name: "F1",
    lng: 116.3,
    lat: 39.8,
    weight: 5,
    alarm_count: 5,
  }),
];

describe("components/CorrelationHeatmap.vue", () => {
  it("renders one heat blob per point with tooltips", () => {
    const wrapper = mount(CorrelationHeatmap, { props: { points } });
    expect(wrapper.find("svg").exists()).toBe(true);
    // 每个点一个 .blob 分组
    expect(wrapper.findAll(".blob").length).toBe(3);
    // 6 档热力渐变 defs
    expect(wrapper.findAll("radialGradient").length).toBe(6);
    // 悬浮提示含根因/项目
    const titles = wrapper.findAll("title").map((t) => t.text());
    expect(titles.some((t) => t.includes("项目A"))).toBe(true);
    expect(titles.some((t) => t.includes("严重"))).toBe(true);
  });

  it("projects points inside the padded canvas (min/max map to edges)", () => {
    const wrapper = mount(CorrelationHeatmap, {
      props: { points, width: 820, height: 360 },
    });
    const cores = wrapper.findAll("circle.core");
    expect(cores.length).toBe(3);
    // 所有点圆心应落在画布范围内（0..W, 0..H）
    for (const c of cores) {
      const cx = Number(c.attributes("cx"));
      const cy = Number(c.attributes("cy"));
      expect(cx).toBeGreaterThanOrEqual(0);
      expect(cx).toBeLessThanOrEqual(820);
      expect(cy).toBeGreaterThanOrEqual(0);
      expect(cy).toBeLessThanOrEqual(360);
    }
  });

  it("emits select with the clicked point", async () => {
    const wrapper = mount(CorrelationHeatmap, { props: { points } });
    await wrapper.findAll(".blob")[0].trigger("click");
    const emitted = wrapper.emitted("select");
    expect(emitted).toBeTruthy();
    // 弱点先画（weight 升序），首个 blob 应是 weight=2 的点(id=1)
    expect((emitted![0][0] as CorrelationHeatPoint).id).toBe(1);
  });

  it("shows an empty placeholder when there are no points", () => {
    const wrapper = mount(CorrelationHeatmap, { props: { points: [] } });
    // 自身热力 SVG 不渲染（el-empty 内部有独立 svg，故用专属类名判定）
    expect(wrapper.find("svg.heat-svg").exists()).toBe(false);
    expect(wrapper.findAll(".blob").length).toBe(0);
    // el-empty 占位
    expect(wrapper.html()).toContain("暂无空间热力数据");
  });

  it("handles a single point without NaN projection", () => {
    const single = [pt({ id: 9, lng: 120.1, lat: 30.2, weight: 4, alarm_count: 4 })];
    const wrapper = mount(CorrelationHeatmap, { props: { points: single } });
    const core = wrapper.find("circle.core");
    expect(core.exists()).toBe(true);
    expect(Number.isNaN(Number(core.attributes("cx")))).toBe(false);
    expect(Number.isNaN(Number(core.attributes("cy")))).toBe(false);
  });
});
