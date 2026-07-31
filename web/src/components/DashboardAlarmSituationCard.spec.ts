// 监控大屏 · 告警态势总览卡单测：加载渲染 KPI+趋势 + 空态 + 跳转联动
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardAlarmSituationCard from "@/components/DashboardAlarmSituationCard.vue";
import type { SituationSummary } from "@/api/alarm";

const hoisted = vi.hoisted(() => ({
  getSituation: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("@/api/alarm", () => ({
  getSituation: (...a: any[]) => hoisted.getSituation(...a),
}));
vi.mock("vue-router", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useRouter: () => ({ push: (...a: any[]) => hoisted.routerPush(...a) }),
  };
});

afterEach(() => {
  hoisted.getSituation.mockReset();
  hoisted.routerPush.mockReset();
});

const EMPTY: SituationSummary = {
  kpi: { today_new: 0, pending: 0, pending_critical: 0, active_preventive: 0 },
  pending_by_level: {},
  trend: [],
};
const SAMPLE: SituationSummary = {
  kpi: { today_new: 5, pending: 12, pending_critical: 2, active_preventive: 1 },
  pending_by_level: { 严重: 2, 警告: 7, 提示: 3 },
  trend: [
    { date: "2026-07-18", total: 3, 严重: 1, 警告: 1, 提示: 1 },
    { date: "2026-07-25", total: 5, 严重: 2, 警告: 2, 提示: 1 },
    { date: "2026-07-31", total: 4, 严重: 1, 警告: 2, 提示: 1 },
  ],
};

describe("DashboardAlarmSituationCard", () => {
  it("加载后渲染 KPI 与按级别堆叠趋势", async () => {
    hoisted.getSituation.mockResolvedValue(SAMPLE);
    const wrapper = mount(DashboardAlarmSituationCard);
    await flushPromises();
    expect(hoisted.getSituation).toHaveBeenCalled();
    const text = wrapper.text();
    expect(text).toContain("今日新增");
    expect(text).toContain("严重待处理");
    expect(text).toContain("5"); // 今日新增
    expect(text).toContain("12"); // 待处理
    // 趋势堆叠面积：3 个级别 → 3 条 path
    expect(wrapper.findAll(".sit-trend-svg path").length).toBe(3);
    expect(wrapper.text()).toContain("待处理按级别");
    wrapper.unmount();
  });

  it("无趋势数据时显示空态", async () => {
    hoisted.getSituation.mockResolvedValue(EMPTY);
    const wrapper = mount(DashboardAlarmSituationCard);
    await flushPromises();
    expect(wrapper.find(".sit-trend-svg").exists()).toBe(false);
    expect(wrapper.text()).toContain("暂无告警趋势");
    wrapper.unmount();
  });

  it("点击「查看全部告警」跳转到告警页", async () => {
    hoisted.getSituation.mockResolvedValue(SAMPLE);
    const wrapper = mount(DashboardAlarmSituationCard);
    await flushPromises();
    await wrapper.find(".sit-foot .el-button").trigger("click");
    expect(hoisted.routerPush).toHaveBeenCalledWith("/alarms");
    wrapper.unmount();
  });
});
