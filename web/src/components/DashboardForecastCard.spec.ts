// 大屏智能预测卡单测：列表加载 + 默认选中最差对象 + 预览联动 + 指标切换重拉
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardForecastCard from "@/components/DashboardForecastCard.vue";
import type { ForecastItem } from "@/api/forecast";

function fc(partial: Partial<ForecastItem>): ForecastItem {
  return {
    id: 1,
    project_id: 1,
    scope_type: "project",
    ref_id: "1",
    name: "示范项目",
    metric: "risk_index",
    horizon_days: 7,
    sample_count: 10,
    last_value: 46,
    slope: 4,
    intercept: 10,
    forecast_value: 74,
    forecast_level: "高",
    std_resid: 1.2,
    forecast_lower: 71.6,
    forecast_upper: 76.4,
    forecast_at: "2026-08-05T02:00:00",
    computed_at: "2026-07-29T03:00:00",
    ...partial,
  };
}

const RISK_ITEMS = [
  fc({ id: 1, ref_id: "1", name: "高风险项目", forecast_value: 74, forecast_level: "高" }),
  fc({ id: 2, ref_id: "2", name: "低风险项目", forecast_value: 20, forecast_level: "低", last_value: 22 }),
];

const HEALTH_ITEMS = [
  fc({
    id: 3,
    scope_type: "device",
    ref_id: "DEV-9",
    name: "良好设备",
    metric: "health_score",
    forecast_value: 88,
    forecast_level: "良",
    last_value: 90,
  }),
  fc({
    id: 4,
    scope_type: "device",
    ref_id: "DEV-1",
    name: "劣化设备",
    metric: "health_score",
    forecast_value: 40,
    forecast_level: "差",
    last_value: 70,
  }),
];

const PREVIEW = {
  scope_type: "project",
  ref_id: "1",
  metric: "risk_index",
  horizon_days: 7,
  series: [
    { at: "2026-07-27T02:00:00", value: 38 },
    { at: "2026-07-28T02:00:00", value: 42 },
    { at: "2026-07-29T02:00:00", value: 46 },
  ],
  forecast: {
    metric: "risk_index",
    horizon_days: 7,
    sample_count: 10,
    last_value: 46,
    slope: 4,
    intercept: 10,
    forecast_value: 74,
    forecast_level: "高",
    std_resid: 1.2,
    forecast_lower: 71.6,
    forecast_upper: 76.4,
    forecast_at: "2026-08-05T02:00:00",
    computed_at: "2026-07-29T03:00:00",
  },
};

const hoisted = vi.hoisted(() => ({
  listForecasts: vi.fn(),
  previewForecast: vi.fn(),
  elError: vi.fn(),
}));

vi.mock("@/api/forecast", () => ({
  listForecasts: (...a: any[]) => hoisted.listForecasts(...a),
  previewForecast: (...a: any[]) => hoisted.previewForecast(...a),
}));
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { error: (...a: any[]) => hoisted.elError(...a), warning: vi.fn(), success: vi.fn(), info: vi.fn() },
  };
});

afterEach(() => {
  hoisted.listForecasts.mockReset();
  hoisted.previewForecast.mockReset();
  hoisted.elError.mockReset();
});

describe("DashboardForecastCard", () => {
  it("挂载后加载风险预测列表并默认选中最高风险 + 拉取预览", async () => {
    hoisted.listForecasts.mockResolvedValue({ items: RISK_ITEMS });
    hoisted.previewForecast.mockResolvedValue(PREVIEW);
    const wrapper = mount(DashboardForecastCard);
    await flushPromises();

    expect(hoisted.listForecasts).toHaveBeenCalledWith({ scope_type: "project", metric: "risk_index" });
    const rows = wrapper.findAll(".fc-row");
    expect(rows.length).toBe(2);
    expect(rows[0].text()).toContain("高风险项目");
    expect(rows[0].classes()).toContain("active");
    // 预览联动（默认选中第一行）
    expect(hoisted.previewForecast).toHaveBeenCalledWith({ ref_id: "1", scope_type: "project" });
    expect(wrapper.find(".fc-chart-meta").text()).toContain("74");
    expect(wrapper.findComponent({ name: "ForecastChart" }).exists()).toBe(true);
    wrapper.unmount();
  });

  it("点击列表行切换预览对象", async () => {
    hoisted.listForecasts.mockResolvedValue({ items: RISK_ITEMS });
    hoisted.previewForecast.mockResolvedValue(PREVIEW);
    const wrapper = mount(DashboardForecastCard);
    await flushPromises();

    await wrapper.findAll(".fc-row")[1].trigger("click");
    await flushPromises();
    expect(hoisted.previewForecast).toHaveBeenLastCalledWith({ ref_id: "2", scope_type: "project" });
    wrapper.unmount();
  });

  it("切换到设备健康：重拉列表且最差设备排前", async () => {
    hoisted.listForecasts.mockResolvedValueOnce({ items: RISK_ITEMS });
    hoisted.previewForecast.mockResolvedValue(PREVIEW);
    const wrapper = mount(DashboardForecastCard);
    await flushPromises();

    hoisted.listForecasts.mockResolvedValueOnce({ items: HEALTH_ITEMS });
    await wrapper.findComponent({ name: "ElRadioGroup" }).setValue("health_score");
    await flushPromises();

    expect(hoisted.listForecasts).toHaveBeenLastCalledWith({ scope_type: "device", metric: "health_score" });
    const rows = wrapper.findAll(".fc-row");
    // health 升序：预测 40 的劣化设备排第一
    expect(rows[0].text()).toContain("劣化设备");
    wrapper.unmount();
  });

  it("无预测数据显示空态提示", async () => {
    hoisted.listForecasts.mockResolvedValue({ items: [] });
    const wrapper = mount(DashboardForecastCard);
    await flushPromises();
    expect(wrapper.text()).toContain("暂无预测数据");
    expect(hoisted.previewForecast).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
