// 监控大屏 · 关联热力时间窗对比卡单测：双窗渲染 + 变化摘要 + 预设切换重拉
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardCorrelationCompareCard from "@/components/DashboardCorrelationCompareCard.vue";

const WIN_A = {
  start: "2026-07-22T00:00:00",
  end: "2026-07-29T00:00:00",
  total: 3,
  cross_device_total: 2,
  alarm_total: 10,
  points: [
    { id: 1, lng: 121.47, lat: 31.23, weight: 5, grid_cell: "3123,12147", spatial_type: "geo", gcj02: { lng: 121.47, lat: 31.23 } },
  ],
};
const WIN_B = {
  start: "2026-07-15T00:00:00",
  end: "2026-07-22T00:00:00",
  total: 1,
  cross_device_total: 1,
  alarm_total: 4,
  points: [],
};
const RESP = {
  window_a: WIN_A,
  window_b: WIN_B,
  diff: {
    new: [{ key: "n1", project_id: 1, project_name: "P1", spatial_type: "geo", scope_text: "网格 121.47,31.23", fence_name: null, grid_cell: "3123,12147", weight: 2, a_weight: undefined, b_weight: 2, delta: 2, a_device_count: 0, b_device_count: 1 }],
    removed: [{ key: "r1", project_id: 1, project_name: "P1", spatial_type: "geo", scope_text: "网格 121.48,31.24", fence_name: null, grid_cell: "3124,12148", weight: 4, a_weight: 4, b_weight: undefined, delta: -4, a_device_count: 2, b_device_count: 0 }],
    changed: [{ key: "c1", project_id: 1, project_name: "P1", spatial_type: "geo", scope_text: "网格 121.47,31.23", fence_name: null, grid_cell: "3123,12147", a_weight: 2, b_weight: 5, delta: 3, a_device_count: 1, b_device_count: 2 }],
  },
};
const EMPTY_RESP = {
  window_a: { ...WIN_A, points: [] },
  window_b: { ...WIN_B, points: [] },
  diff: { new: [], removed: [], changed: [] },
};

const hoisted = vi.hoisted(() => ({
  getCorrelationCompare: vi.fn(),
  elError: vi.fn(),
}));

vi.mock("@/api/metrics", () => ({
  getCorrelationCompare: (...a: any[]) => hoisted.getCorrelationCompare(...a),
}));
vi.mock("@/components/CorrelationHeatmap.vue", () => ({
  default: { name: "CorrelationHeatmap", props: ["points", "width", "height"], template: `<div class="hm-stub">{{ points.length }}</div>` },
}));
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, ElMessage: { error: (...a: any[]) => hoisted.elError(...a), warning: vi.fn(), success: vi.fn(), info: vi.fn() } };
});

afterEach(() => {
  hoisted.getCorrelationCompare.mockReset();
  hoisted.elError.mockReset();
});

describe("DashboardCorrelationCompareCard", () => {
  it("挂载后加载并渲染双窗热力与变化摘要", async () => {
    hoisted.getCorrelationCompare.mockResolvedValue(RESP);
    const wrapper = mount(DashboardCorrelationCompareCard);
    await flushPromises();
    expect(hoisted.getCorrelationCompare).toHaveBeenCalledTimes(1);
    // 双窗热力均渲染（Stub 显示 points 长度）
    expect(wrapper.findAll(".hm-stub").length).toBe(2);
    // 变化摘要统计
    expect(wrapper.find(".diff-chip.new").text()).toContain("1");
    expect(wrapper.find(".diff-chip.removed").text()).toContain("1");
    expect(wrapper.find(".diff-chip.changed").text()).toContain("1");
    // 变化行展示 scope_text
    expect(wrapper.find(".diff-scope").text()).toContain("网格 121.47,31.23");
    wrapper.unmount();
  });

  it("无显著变化时显示空态", async () => {
    hoisted.getCorrelationCompare.mockResolvedValue(EMPTY_RESP);
    const wrapper = mount(DashboardCorrelationCompareCard);
    await flushPromises();
    expect(wrapper.find(".diff-empty").exists()).toBe(true);
    wrapper.unmount();
  });

  it("切换预设会重新调用对比接口", async () => {
    hoisted.getCorrelationCompare.mockResolvedValue(RESP);
    const wrapper = mount(DashboardCorrelationCompareCard);
    await flushPromises();
    expect(hoisted.getCorrelationCompare).toHaveBeenCalledTimes(1);
    await wrapper.findComponent({ name: "ElSelect" }).setValue("30d");
    await flushPromises();
    expect(hoisted.getCorrelationCompare).toHaveBeenCalledTimes(2);
    const last = hoisted.getCorrelationCompare.mock.calls[1][0];
    expect(last).toMatchObject({ only_cross_device: true });
    wrapper.unmount();
  });
});
