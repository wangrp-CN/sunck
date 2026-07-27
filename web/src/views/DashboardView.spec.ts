// DashboardView 单测（仪表盘：加载统计/近期告警/地图 + 粒度联动 + 快照导出）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DashboardView from "@/views/DashboardView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElNotification: vi.fn(),
  };
});

const stats = {
  counts: { projects: 2, devices: 5, alarms: 10, alarms_window: 8, alarms_today: 3, alarms_current_period: 3 },
  alarm_by_level: [{ level: "警告", count: 2 }],
  alarm_by_handle: [{ status: "待处理", count: 1 }],
  device_by_type: [{ type: "locate", count: 3 }],
  alarm_trend_period: [{ period: "2026-07-21", count: 3 }],
  device_stats: { online_rate: 80, online: 4, total: 5, window_active: 3 },
  fence_stats: { monitored: 2 },
  trend_start: "2026-07-15",
  trend_end: "2026-07-21",
  current_period: "2026-07-21",
  anomaly_params: { k: 2.0, window: 7, min_trailing: 3, min_points: 5 },
};
const recent = {
  items: [
    { id: 1, alarm_time: "2026-07-21T10:00:00", device_no: "LOC-1", alarm_level: "警告", alarm_info: "x" },
  ],
  total: 1,
};

vi.mock("@/api/dashboard", () => ({
  getDashboardStats: vi.fn(),
  getRecentAlarms: vi.fn(),
  getEffectiveness: vi.fn(),
}));
vi.mock("@/api/metrics", () => ({
  getRiskAlerts: vi.fn(),
  getRiskTrend: vi.fn(),
  getCorrelationSummary: vi.fn(),
  getCorrelationTrend: vi.fn(),
  RISK_ALERT_THRESHOLD: 60,
}));
vi.mock("@/api/realtime", () => ({
  fetchDevices: vi.fn(),
  fetchLocations: vi.fn(),
  DEVICE_TYPE_LABELS: { locate: "人机定位", anti_intrusion: "大机防侵限", train_approach: "列车接近" },
}));
vi.mock("@/api/fence", () => ({ fetchFences: vi.fn() }));
vi.mock("@/api/alarm", () => ({
  exportAlarmReport: vi.fn(),
  fetchSnapshotPreview: vi.fn(),
}));
vi.mock("@/components/MapPanel.vue", () => ({ default: { name: "M", template: "<div/>", methods: { focusDevice() {} } } }));
vi.mock("@/components/WorkPlanPopup.vue", () => ({ default: { name: "WPP", template: "<div/>" } }));
vi.mock("@/components/DailyTrendChart.vue", () => ({ default: { name: "DTC", template: "<div/>" } }));

import { getDashboardStats, getRecentAlarms, getEffectiveness } from "@/api/dashboard";
import { getRiskAlerts, getRiskTrend, getCorrelationSummary, getCorrelationTrend } from "@/api/metrics";
import { fetchDevices, fetchLocations } from "@/api/realtime";
import { fetchFences } from "@/api/fence";
import { exportAlarmReport, fetchSnapshotPreview } from "@/api/alarm";

// el-dialog 在 jsdom 下卸载时过渡 vnode 为 null 会抛未处理异常（已知环境问题）。
// 用无过渡的占位替换 ElDialog，使弹层相关断言仍成立且不再崩溃。
const baseMount = () =>
  mount(DashboardView, {
    global: { stubs: { ElDialog: { template: "<div class='dlg-stub'><slot /></div>" } } },
  });

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getDashboardStats).mockResolvedValue(stats as any);
  vi.mocked(getRecentAlarms).mockResolvedValue(recent as any);
  vi.mocked(getRiskAlerts).mockResolvedValue({ items: [] } as any);
  vi.mocked(getRiskTrend).mockResolvedValue({ series: [] } as any);
  vi.mocked(getCorrelationSummary).mockResolvedValue({ total: 0, cross_device_total: 0, today_cross_device: 0, today_projects: 0, by_level: {} } as any);
  vi.mocked(getCorrelationTrend).mockResolvedValue({ days: 30, only_cross_device: true, series: [] } as any);
  vi.mocked(fetchDevices).mockResolvedValue({ items: [], total: 0 } as any);
  vi.mocked(fetchLocations).mockResolvedValue({ items: [], total: 0 } as any);
  vi.mocked(fetchFences).mockResolvedValue({ items: [], total: 0 } as any);
  vi.mocked(getEffectiveness).mockResolvedValue({
    days: 30,
    range_start: "2026-06-27T00:00:00+08:00",
    range_end: "2026-07-27T23:59:59+08:00",
    storm: { suppressed: 12, alarms: 40, rate_pct: 23.1 },
    mttr: { avg_hours: 5.5, resolved: 30, resolution_rate_pct: 75.0 },
    dispatch_sla: { closed: 8, on_time: 7, sla_rate_pct: 87.5, avg_cycle_hours: 4.0 },
    hazard: { total: 10, closed: 6, closure_rate_pct: 60.0, on_time_rate_pct: 83.3 },
    anomaly: { alarms: 4, share_pct: 10.0, correlation_dispatches: 2 },
    computed_at: "2026-07-27T13:00:00+00:00",
  } as any);
  vi.mocked(exportAlarmReport).mockResolvedValue(new Blob(["x"]));
  vi.mocked(fetchSnapshotPreview).mockResolvedValue({
    meta: { filters_desc: "全部", generated_at: "2026-07-21T10:00:00" },
    period_keys: ["2026-07-21"],
    granularity: "day",
    summary: { total: 5, handled: 3, pending: 2, handle_rate: 0.6 },
    periods: [
      {
        period: "2026-07-21",
        count: 5,
        by_type: { fence_intrusion: 1, distance_too_close: 2, device_alarm: 2 },
        pending: 2,
        handled: 3,
        by_project: [],
      },
    ],
    project_summary: [
      {
        project_id: 1,
        count: 5,
        by_type: { fence_intrusion: 1, distance_too_close: 2, device_alarm: 2 },
      },
    ],
  } as any);
  // jsdom 未实现 URL.createObjectURL，download 流程需要
  (URL as any).createObjectURL = vi.fn(() => "blob:x");
  (URL as any).revokeObjectURL = vi.fn();
});
afterEach(() => {
  // el-dialog 在 jsdom 下卸载时过渡 vnode 为 null 会抛错（已知环境问题，非组件缺陷）；
  // 测试断言已在测试函数内完成，此处吞掉卸载期的过渡 teardown 异常。
  try {
    wrapper?.unmount();
  } catch {
    /* jsdom + element-plus el-dialog 过渡卸载已知问题 */
  }
  wrapper = null;
});

describe("views/DashboardView.vue", () => {
  it("挂载后并行加载统计 + 近期告警 + 地图数据", async () => {
    wrapper = baseMount();
    await flushPromises();
    expect(vi.mocked(getDashboardStats)).toHaveBeenCalled();
    expect(vi.mocked(getRecentAlarms)).toHaveBeenCalled();
    expect(vi.mocked(fetchDevices)).toHaveBeenCalled();
    expect(vi.mocked(fetchLocations)).toHaveBeenCalled();
    expect(vi.mocked(fetchFences)).toHaveBeenCalled();
    const vm = wrapper.vm as any;
    expect(vm.stats).not.toBeNull();
    expect(vm.recent.length).toBe(1);
    expect(vm.counts.projects).toBe(2);
  });

  it("切换粒度（week）重新拉取并设定对应时间范围", async () => {
    wrapper = baseMount();
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.trendGranularity = "week";
    await vm.onGranularityChange();
    await flushPromises();
    expect(vi.mocked(getDashboardStats)).toHaveBeenLastCalledWith(
      expect.objectContaining({ granularity: "week" }),
    );
    expect(Array.isArray(vm.trendRange)).toBe(true);
    expect(vm.trendRange.length).toBe(2);
  });

  it("defaultRangeFor 返回 [start,end] 日期串", () => {
    wrapper = baseMount();
    const vm = wrapper.vm as any;
    const day = vm.defaultRangeFor("day");
    expect(day).toHaveLength(2);
    expect(day[0]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("导出快照：需先设定范围，调用 exportAlarmReport(snapshot:true)", async () => {
    wrapper = baseMount();
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.trendRange = ["2026-01-01", "2026-01-31"];
    await vm.doExportSnapshot("excel");
    expect(vi.mocked(exportAlarmReport)).toHaveBeenCalledWith(
      "excel",
      expect.objectContaining({ snapshot: true }),
    );
  });

  it("未设范围导出被拦截", async () => {
    wrapper = baseMount();
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.trendRange = null;
    await vm.doExportSnapshot("excel");
    expect(vi.mocked(exportAlarmReport)).not.toHaveBeenCalled();
  });

  it("打开快照预览：拉取 fetchSnapshotPreview 并置可见", async () => {
    wrapper = baseMount();
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.trendRange = ["2026-01-01", "2026-01-31"];
    await vm.openSnapshotPreview();
    await flushPromises();
    expect(vi.mocked(fetchSnapshotPreview)).toHaveBeenCalled();
    expect(vm.snapPreviewVisible).toBe(true);
  });

  it("趋势异常检测：聚合四类序列异常点，k 阈值可调", async () => {
    // 用多周期趋势构造一条尾部突增，验证 anomalyList 命中
    const richStats = {
      ...(stats as any),
      alarm_trend_period: [
        { period: "2026-07-15", count: 8 },
        { period: "2026-07-16", count: 12 },
        { period: "2026-07-17", count: 8 },
        { period: "2026-07-18", count: 12 },
        { period: "2026-07-19", count: 8 },
        { period: "2026-07-20", count: 12 },
        { period: "2026-07-21", count: 15 },
      ],
      device_trend_period: [
        { period: "2026-07-15", active: 5 },
        { period: "2026-07-16", active: 5 },
        { period: "2026-07-17", active: 5 },
        { period: "2026-07-18", active: 5 },
        { period: "2026-07-19", active: 5 },
        { period: "2026-07-20", active: 5 },
        { period: "2026-07-21", active: 5 },
      ],
    };
    vi.mocked(getDashboardStats).mockResolvedValueOnce(richStats as any);
    wrapper = baseMount();
    await flushPromises();
    const vm = wrapper.vm as any;
    // 默认 k=2.0 下，告警量尾部 30 远超基线 → 至少 1 个异常
    expect(vm.anomalyList.length).toBeGreaterThanOrEqual(1);
    expect(vm.anomalyList[0].label).toBe("告警量");
    expect(vm.anomalyList[0].direction).toBe("spike");
    // 调高 k 到 3.0 后，偏离被吸收 → 异常消失
    vm.anomalyK = 3.0;
    await flushPromises();
    expect(vm.anomalyList.length).toBe(0);
  });

  it("闭环效能度量卡：加载并渲染五项指标 + 窗口切换重拉", async () => {
    wrapper = baseMount();
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vm.eff).not.toBeNull();
    expect(vm.eff.storm.rate_pct).toBe(23.1);
    expect(vm.eff.mttr.avg_hours).toBe(5.5);
    // 模板含五项标签
    const text = wrapper.text();
    expect(text).toContain("告警风暴抑制率");
    expect(text).toContain("告警平均处置时长");
    expect(text).toContain("派单 SLA 达成率");
    expect(text).toContain("隐患治理闭环率");
    expect(text).toContain("异常引擎告警占比");
    // 切换窗口 → 重新拉取（带参）
    vm.effDays = 7;
    await flushPromises();
    expect(vi.mocked(getEffectiveness)).toHaveBeenLastCalledWith(7);
  });
});
