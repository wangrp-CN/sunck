// 大屏预测模型 A/B 对比卡单测：加载渲染 + 空态 + 重新回测联动
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardABHitRateCard from "@/views/DashboardABHitRateCard.vue";
import type { ABHitRate } from "@/api/forecast";

const AB_DATA: ABHitRate = {
  period_days: 90,
  generated_at: "2026-07-31T03:00:00",
  models: [
    {
      model_version: "ols_v1",
      label: "OLS 线性",
      verifiable: 4,
      hits: 2,
      false_positives: 2,
      pending: 0,
      hit_rate: 0.5,
      false_positive_rate: 0.5,
      avg_lead_hours: 30.0,
      by_metric: {},
    },
    {
      model_version: "hw_v1",
      label: "Holt-Winters 季节趋势",
      verifiable: 4,
      hits: 3,
      false_positives: 1,
      pending: 0,
      hit_rate: 0.75,
      false_positive_rate: 0.25,
      avg_lead_hours: 34.0,
      by_metric: {},
    },
  ],
  comparison: {
    baseline: "ols_v1",
    baseline_label: "OLS 线性",
    challenger: "hw_v1",
    challenger_label: "Holt-Winters 季节趋势",
    hit_rate_baseline: 0.5,
    hit_rate_challenger: 0.75,
    hit_rate_delta: 0.25,
    hit_rate_delta_pct: 50,
    false_positive_rate_baseline: 0.5,
    false_positive_rate_challenger: 0.25,
    false_positive_rate_delta: -0.25,
    avg_lead_hours_baseline: 30,
    avg_lead_hours_challenger: 34,
    lead_delta_hours: 4,
    better: true,
    summary: "命中率+25pp（提升）；误报率-25pp（下降）；平均提前量+4.0h",
  },
};

const EMPTY: ABHitRate = {
  period_days: 90,
  generated_at: "2026-07-31T03:00:00",
  models: [
    { model_version: "ols_v1", label: "OLS 线性", verifiable: 0, hits: 0, false_positives: 0, pending: 0, hit_rate: null, false_positive_rate: null, avg_lead_hours: null, by_metric: {} },
    { model_version: "hw_v1", label: "Holt-Winters 季节趋势", verifiable: 0, hits: 0, false_positives: 0, pending: 0, hit_rate: null, false_positive_rate: null, avg_lead_hours: null, by_metric: {} },
  ],
  comparison: null,
};

const hoisted = vi.hoisted(() => ({
  getForecastABHitRate: vi.fn(),
  runForecastBacktest: vi.fn(),
  getForecastDefaultModel: vi.fn(),
  setForecastDefaultModel: vi.fn(),
  elSuccess: vi.fn(),
  elError: vi.fn(),
}));

vi.mock("@/api/forecast", () => ({
  getForecastABHitRate: (...a: any[]) => hoisted.getForecastABHitRate(...a),
  runForecastBacktest: (...a: any[]) => hoisted.runForecastBacktest(...a),
  getForecastDefaultModel: (...a: any[]) => hoisted.getForecastDefaultModel(...a),
  setForecastDefaultModel: (...a: any[]) => hoisted.setForecastDefaultModel(...a),
}));
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: {
      success: (...a: any[]) => hoisted.elSuccess(...a),
      error: (...a: any[]) => hoisted.elError(...a),
      warning: vi.fn(),
      info: vi.fn(),
    },
  };
});

afterEach(() => {
  hoisted.getForecastABHitRate.mockReset();
  hoisted.runForecastBacktest.mockReset();
  hoisted.getForecastDefaultModel.mockReset();
  hoisted.setForecastDefaultModel.mockReset();
  hoisted.elSuccess.mockReset();
  hoisted.elError.mockReset();
});

describe("DashboardABHitRateCard", () => {
  it("挂载后加载 A/B 报表并渲染两模型列与增量对比", async () => {
    hoisted.getForecastABHitRate.mockResolvedValue(AB_DATA);
    const wrapper = mount(DashboardABHitRateCard);
    await flushPromises();

    expect(hoisted.getForecastABHitRate).toHaveBeenCalledWith({ days: 90 });
    const cols = wrapper.findAll(".model-col");
    expect(cols.length).toBe(2);
    expect(cols[0].text()).toContain("OLS 线性");
    expect(cols[0].text()).toContain("50%");
    expect(cols[1].text()).toContain("Holt-Winters 季节趋势");
    expect(cols[1].text()).toContain("75%");
    expect(wrapper.find(".cmp-banner").text()).toContain("命中率+25pp");
    expect(wrapper.findAll(".delta-row .el-tag").length).toBe(3);
    wrapper.unmount();
  });

  it("无回测数据时空态提示，不渲染模型列", async () => {
    hoisted.getForecastABHitRate.mockResolvedValue(EMPTY);
    const wrapper = mount(DashboardABHitRateCard);
    await flushPromises();

    expect(wrapper.find(".model-col").exists()).toBe(false);
    expect(wrapper.text()).toContain("暂无回测数据");
    wrapper.unmount();
  });

  it("点击重新回测：调用回测接口并刷新报表", async () => {
    hoisted.getForecastABHitRate.mockResolvedValue(EMPTY);
    hoisted.runForecastBacktest.mockResolvedValue({ models: ["ols_v1", "hw_v1"], anchors: 10, rows: 8, by_model: {}, horizon_days: 7 });
    const wrapper = mount(DashboardABHitRateCard);
    await flushPromises();

    await wrapper.find(".el-button").trigger("click");
    await flushPromises();

    expect(hoisted.runForecastBacktest).toHaveBeenCalledWith({ days: 90, horizon_days: 7 });
    expect(hoisted.elSuccess).toHaveBeenCalled();
    expect(hoisted.getForecastABHitRate).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("hw_v1 更优且未上线时显示一键切换建议，点击调用切换接口并刷新", async () => {
    hoisted.getForecastABHitRate.mockResolvedValue(AB_DATA);
    hoisted.getForecastDefaultModel.mockResolvedValue({
      model_version: "ols_v1",
      available: [
        { model_version: "ols_v1", label: "OLS 线性" },
        { model_version: "hw_v1", label: "Holt-Winters 季节趋势" },
      ],
    });
    hoisted.setForecastDefaultModel.mockResolvedValue({ model_version: "hw_v1" });
    const wrapper = mount(DashboardABHitRateCard);
    await flushPromises();

    // 头部展示当前线上模型
    expect(wrapper.find(".online-tag").text()).toContain("OLS 线性");
    // 切换建议横幅可见
    const switchBanner = wrapper.find(".switch-banner");
    expect(switchBanner.exists()).toBe(true);
    expect(switchBanner.text()).toContain("一键切换");

    await switchBanner.find(".el-button").trigger("click");
    await flushPromises();

    expect(hoisted.setForecastDefaultModel).toHaveBeenCalledWith("hw_v1");
    expect(hoisted.elSuccess).toHaveBeenCalled();
    expect(hoisted.getForecastDefaultModel).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
});
