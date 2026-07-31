// 监控大屏 · 活跃预防式告警卡单测：加载渲染 + 空态 + 跳转联动
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardPreventiveCard from "@/components/DashboardPreventiveCard.vue";
import type { PreventiveSummary } from "@/api/alarm";

const hoisted = vi.hoisted(() => ({
  getPreventiveSummary: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("@/api/alarm", () => ({
  getPreventiveSummary: (...a: any[]) => hoisted.getPreventiveSummary(...a),
}));
vi.mock("vue-router", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useRouter: () => ({ push: (...a: any[]) => hoisted.routerPush(...a) }),
  };
});

afterEach(() => {
  hoisted.getPreventiveSummary.mockReset();
  hoisted.routerPush.mockReset();
});

const EMPTY: PreventiveSummary = { total: 0, by_metric: {}, by_level: {}, recent: [] };
const SAMPLE: PreventiveSummary = {
  total: 3,
  by_metric: { risk_index: 2, health_score: 1 },
  by_level: { 警告: 2, 严重: 1 },
  recent: [
    {
      id: 1,
      project_id: 1,
      alarm_type: "preventive_alert",
      device_no: "preventive:risk_index:P1:7",
      alarm_info: "项目风险指数将在 7 天后越阈",
      alarm_level: "警告",
      alarm_time: "2026-07-30T08:00:00",
    } as any,
  ],
};

describe("DashboardPreventiveCard", () => {
  it("加载后渲染活跃总数与指标分布", async () => {
    hoisted.getPreventiveSummary.mockResolvedValue(SAMPLE);
    const wrapper = mount(DashboardPreventiveCard);
    await flushPromises();
    expect(hoisted.getPreventiveSummary).toHaveBeenCalled();
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("项目风险指数");
    expect(wrapper.text()).toContain("设备健康分");
    wrapper.unmount();
  });

  it("total 为 0 时显示绿色 0 与空态", async () => {
    hoisted.getPreventiveSummary.mockResolvedValue(EMPTY);
    const wrapper = mount(DashboardPreventiveCard);
    await flushPromises();
    expect(wrapper.find(".prev-bignum.zero").exists()).toBe(true);
    expect(wrapper.text()).toContain("暂无活跃预防式告警");
    wrapper.unmount();
  });

  it("点击「查看全部明细」跳转到告警页预防式筛选", async () => {
    hoisted.getPreventiveSummary.mockResolvedValue(SAMPLE);
    const wrapper = mount(DashboardPreventiveCard);
    await flushPromises();
    await wrapper.find(".prev-foot .el-button").trigger("click");
    expect(hoisted.routerPush).toHaveBeenCalledWith("/alarms?alarm_type=preventive_alert");
    wrapper.unmount();
  });
});
