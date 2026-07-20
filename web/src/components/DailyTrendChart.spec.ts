import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import DailyTrendChart from "@/components/DailyTrendChart.vue";

type TDayPoint = {
  date?: string;
  period?: string;
  count: number;
  by_type?: Record<string, number>;
  by_level?: Record<string, number>;
};

const dayData: TDayPoint[] = [
  {
    period: "2026-07-15",
    count: 2,
    by_type: { fence_intrusion: 1, device_alarm: 1 },
    by_level: { 严重: 1, 提示: 1 },
  },
  {
    period: "2026-07-16",
    count: 3,
    by_type: { fence_intrusion: 1, distance_too_close: 1, device_alarm: 1 },
    by_level: { 严重: 1, 警告: 1, 提示: 1 },
  },
];

const weekData: TDayPoint[] = [
  { period: "2026-W28", count: 1, by_type: { fence_intrusion: 1 }, by_level: { 严重: 1 } },
  { period: "2026-W29", count: 2, by_type: { device_alarm: 2 }, by_level: { 提示: 2 } },
];

describe("components/DailyTrendChart.vue", () => {
  it("renders one column per period and emits the period key on click (day)", async () => {
    const wrapper = mount(DailyTrendChart, {
      props: { data: dayData, field: "by_type", granularity: "day" },
    });
    const cols = wrapper.findAll(".col");
    expect(cols.length).toBe(2);
    // X 轴按天格式化为 MM-DD
    expect(wrapper.text()).toContain("07-16");

    await cols[0].trigger("click");
    const emitted = wrapper.emitted("bar-click");
    expect(emitted).toBeTruthy();
    expect(emitted![0]).toEqual(["2026-07-15"]);
  });

  it("renders week granularity with Wxx labels and emits ISO week key", async () => {
    const wrapper = mount(DailyTrendChart, {
      props: { data: weekData, field: "by_type", granularity: "week" },
    });
    expect(wrapper.findAll(".col").length).toBe(2);
    expect(wrapper.text()).toContain("W29");

    await wrapper.findAll(".col")[1].trigger("click");
    expect(wrapper.emitted("bar-click")![0]).toEqual(["2026-W29"]);
  });

  it("renders stacked bars per category (by_type)", () => {
    const wrapper = mount(DailyTrendChart, {
      props: { data: dayData, field: "by_type", granularity: "day" },
    });
    // 列0: fence_intrusion + device_alarm = 2；列1: 三类型 = 3 → 共 5 段
    expect(wrapper.findAll(".bar").length).toBe(5);
  });

  it("falls back to date field when period is absent", async () => {
    const legacy = [{ date: "2026-07-10", count: 1, by_type: { fence_intrusion: 1 } }];
    const wrapper = mount(DailyTrendChart, {
      props: { data: legacy, field: "by_type", granularity: "day" },
    });
    await wrapper.find(".col").trigger("click");
    expect(wrapper.emitted("bar-click")![0]).toEqual(["2026-07-10"]);
  });

  it("renders one column per period across multiple buckets (多周期自证)", () => {
    const multi: TDayPoint[] = [
      { period: "2026-W20", count: 3, by_type: { fence_intrusion: 2, device_alarm: 1 }, by_level: { 严重: 2, 提示: 1 } },
      { period: "2026-W24", count: 5, by_type: { distance_too_close: 3, fence_intrusion: 2 }, by_level: { 警告: 3, 严重: 2 } },
      { period: "2026-W28", count: 2, by_type: { device_alarm: 2 }, by_level: { 提示: 2 } },
      { period: "2026-W30", count: 4, by_type: { fence_intrusion: 4 }, by_level: { 严重: 4 } },
    ];
    const wrapper = mount(DailyTrendChart, {
      props: { data: multi, field: "by_type", granularity: "week" },
    });
    // 多周期 → 多列（每周期一列），且每列堆叠段总数 = 各类出现段数之和
    expect(wrapper.findAll(".col").length).toBe(4);
    expect(wrapper.text()).toContain("W20");
    expect(wrapper.text()).toContain("W30");
    // 堆叠段：列0 2段 + 列1 2段 + 列2 1段 + 列3 1段 = 6
    expect(wrapper.findAll(".bar").length).toBe(6);
  });
});
