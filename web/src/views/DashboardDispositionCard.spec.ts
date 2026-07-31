// 大屏处置效果闭环卡单测：统计加载 + 闭环率/时长指标 + 按结果分布 + 按项目闭环率
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardDispositionCard from "@/views/DashboardDispositionCard.vue";
import type { DispositionStats } from "@/api/disposition";

const STATS: DispositionStats = {
  period_days: 30,
  total: 10,
  resolved: 6,
  closure_rate: 0.6,
  avg_duration_hours: 3.5,
  by_outcome: { 已解决: 6, 部分解决: 2, 未解决: 1, 误报: 1 },
  by_handler: [{ handler_id: 1, total: 10, resolved: 6, closure_rate: 0.6 }],
  by_project: [
    { project_id: 1, total: 5, resolved: 4, closure_rate: 0.8 },
    { project_id: 2, total: 3, resolved: 1, closure_rate: 0.333 },
    { project_id: 0, total: 2, resolved: 1, closure_rate: 0.5 }, // 未分配，应被过滤
  ],
};

const PROJECTS = {
  items: [
    { id: 1, name: "示范项目" },
    { id: 2, name: "二号项目" },
  ],
};

const hoisted = vi.hoisted(() => ({
  getDispositionStats: vi.fn(),
  fetchProjects: vi.fn(),
}));

vi.mock("@/api/disposition", () => ({
  getDispositionStats: (...a: any[]) => hoisted.getDispositionStats(...a),
}));
vi.mock("@/api/project", () => ({
  fetchProjects: (...a: any[]) => hoisted.fetchProjects(...a),
}));

afterEach(() => {
  hoisted.getDispositionStats.mockReset();
  hoisted.fetchProjects.mockReset();
});

describe("DashboardDispositionCard", () => {
  it("挂载后加载统计并展示闭环率/处置总数/已解决/平均时长/待改进", async () => {
    hoisted.getDispositionStats.mockResolvedValue(STATS);
    hoisted.fetchProjects.mockResolvedValue(PROJECTS);
    const wrapper = mount(DashboardDispositionCard);
    await flushPromises();

    expect(hoisted.getDispositionStats).toHaveBeenCalledWith({ days: 30 });
    expect(hoisted.fetchProjects).toHaveBeenCalledWith({ size: 200 });

    const text = wrapper.text();
    expect(text).toContain("60%"); // 闭环率
    expect(text).toContain("处置总数");
    expect(text).toContain("已解决");
    expect(text).toContain("3.5 h"); // 平均处置时长
    expect(text).toContain("4"); // 待改进 = 10 - 6
    wrapper.unmount();
  });

  it("按处置结果显示分布条（已解决/部分解决/未解决/误报）", async () => {
    hoisted.getDispositionStats.mockResolvedValue(STATS);
    hoisted.fetchProjects.mockResolvedValue(PROJECTS);
    const wrapper = mount(DashboardDispositionCard);
    await flushPromises();

    const rows = wrapper.findAll(".oc-row");
    // 已解决 / 部分解决 / 未解决 / 误报 = 4 条（无「未填写」）
    expect(rows.length).toBe(4);
    const names = rows.map((r) => r.find(".oc-name").text());
    expect(names).toContain("已解决");
    expect(names).toContain("误报");
    wrapper.unmount();
  });

  it("按项目闭环率 Top6 且映射项目名、过滤未分配项目", async () => {
    hoisted.getDispositionStats.mockResolvedValue(STATS);
    hoisted.fetchProjects.mockResolvedValue(PROJECTS);
    const wrapper = mount(DashboardDispositionCard);
    await flushPromises();

    const rows = wrapper.findAll(".bp-row");
    expect(rows.length).toBe(2); // project_id=0 被过滤
    const names = rows.map((r) => r.find(".bp-name").text());
    expect(names).toContain("示范项目");
    expect(names).toContain("二号项目");
    expect(wrapper.text()).toContain("80%"); // 示范项目闭环率 0.8
    expect(wrapper.text()).toContain("33%"); // 二号项目闭环率 0.333
    wrapper.unmount();
  });

  it("无数据显示空态提示", async () => {
    hoisted.getDispositionStats.mockRejectedValue(new Error("network"));
    hoisted.fetchProjects.mockResolvedValue(PROJECTS);
    const wrapper = mount(DashboardDispositionCard);
    await flushPromises();
    expect(wrapper.text()).toContain("暂无处置数据");
    expect(hoisted.getDispositionStats).toHaveBeenCalled();
    wrapper.unmount();
  });
});
