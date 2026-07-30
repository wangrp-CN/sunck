// 预测图单测：历史线 + 预测虚线 + 置信带 + 阈值线 + 空态
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ForecastChart from "@/components/ForecastChart.vue";
import type { ForecastFit, ForecastSeriesPoint } from "@/api/forecast";

const SERIES: ForecastSeriesPoint[] = [
  { at: "2026-07-20T02:00:00", value: 10 },
  { at: "2026-07-21T02:00:00", value: 14 },
  { at: "2026-07-22T02:00:00", value: 18 },
  { at: "2026-07-23T02:00:00", value: 22 },
];

const FIT: ForecastFit = {
  metric: "risk_index",
  horizon_days: 7,
  sample_count: 4,
  last_value: 22,
  slope: 4,
  intercept: 10,
  forecast_value: 50,
  forecast_level: "中",
  std_resid: 2.5,
  forecast_lower: 45.1,
  forecast_upper: 54.9,
  forecast_at: "2026-07-30T02:00:00",
  computed_at: "2026-07-23T03:00:00",
};

describe("ForecastChart", () => {
  it("渲染历史线、预测虚线、置信带、预测点与阈值线", () => {
    const wrapper = mount(ForecastChart, {
      props: { series: SERIES, forecast: FIT, threshold: 60 },
    });
    expect(wrapper.find("svg.forecast-chart").exists()).toBe(true);
    expect(wrapper.find(".fc-line").exists()).toBe(true);
    expect(wrapper.find(".fc-proj").exists()).toBe(true);
    expect(wrapper.find(".fc-band").exists()).toBe(true);
    expect(wrapper.find(".fc-threshold").exists()).toBe(true);
    // 预测值 / 上下界标注
    expect(wrapper.find(".fc-value").text()).toBe("50");
    const bounds = wrapper.findAll(".fc-bound").map((b) => b.text());
    expect(bounds).toContain("55");
    expect(bounds).toContain("45");
    // x 轴含预测日期（07-30 高亮）
    expect(wrapper.find(".fc-x-label.fc").text()).toBe("07-30");
  });

  it("forecast 为 null 时仅画历史线，无预测元素", () => {
    const wrapper = mount(ForecastChart, {
      props: { series: SERIES, forecast: null },
    });
    expect(wrapper.find(".fc-line").exists()).toBe(true);
    expect(wrapper.find(".fc-proj").exists()).toBe(false);
    expect(wrapper.find(".fc-band").exists()).toBe(false);
    expect(wrapper.find(".fc-value").exists()).toBe(false);
    // 未传阈值则无阈值线
    expect(wrapper.find(".fc-threshold").exists()).toBe(false);
  });

  it("空序列显示空态", () => {
    const wrapper = mount(ForecastChart, { props: { series: [], forecast: null } });
    expect(wrapper.find("svg").exists()).toBe(false);
    expect(wrapper.find(".fc-empty").text()).toContain("暂无快照序列");
  });
});
