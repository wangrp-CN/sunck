import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AlarmView from "@/views/AlarmView.vue";
import { fetchAlarms } from "@/api/realtime";
import {
  exportAlarmReport,
  fetchAlarmReport,
  fetchAlarmTrend,
  fetchSnapshotPreview,
} from "@/api/alarm";
import type { SnapshotPreviewResult } from "@/api/alarm";

// 仅替换 ElMessage，保留 element-plus 其余组件导出
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});
vi.mock("@/api/realtime", () => ({
  DEVICE_TYPE_LABELS: {},
  fetchAlarms: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  fetchDevices: vi.fn().mockResolvedValue({ items: [] }),
  fetchLocations: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/api/alarm", () => ({
  exportAlarmReport: vi.fn(),
  fetchAlarmPeriod: vi.fn().mockResolvedValue({ items: [] }),
  fetchAlarmReport: vi.fn(),
  fetchAlarmTrend: vi.fn().mockResolvedValue({
    summary: { by_period: [{ period: "2026-07-01", count: 5, by_type: {} }] },
  }),
  fetchSnapshotPreview: vi.fn(),
  getAlarmConfig: vi.fn().mockResolvedValue({}),
  handleAlarm: vi.fn().mockResolvedValue(undefined),
  updateAlarmConfig: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@/api/project", () => ({
  fetchProjects: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/api/fence", () => ({
  fetchFences: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/api/media", () => ({
  putAlarmMedia: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    user: { permission_codes: ["alarm:handle", "alarm:config", "alarm:list"] },
    loadProfile: vi.fn().mockResolvedValue(undefined),
  }),
}));

const snapshotFixture: SnapshotPreviewResult = {
  granularity: "month",
  period_keys: ["2026-05", "2026-06"],
  meta: {
    title: "告警历史快照",
    generated_at: "2026-07-17 10:30:00",
    filters_desc: "全部项目",
  },
  summary: {
    total: 648,
    handled: 206,
    pending: 442,
    handle_rate: 0.318,
    by_type: { fence_intrusion: 100, distance_too_close: 50, device_alarm: 498 },
    by_level: {},
    by_handle_status: {},
  },
  periods: [
    {
      period: "2026-05",
      total: 109,
      by_type: { fence_intrusion: 40, device_alarm: 69 } as any,
      by_level: {},
      pending: 80,
      handled: 29,
      by_project: [],
    },
    {
      period: "2026-06",
      total: 106,
      by_type: { fence_intrusion: 30, distance_too_close: 26, device_alarm: 50 },
      by_level: {},
      pending: 90,
      handled: 16,
      by_project: [],
    },
  ],
  project_summary: [
    {
      project_name: "示例项目A",
      count: 200,
      ratio: 0.3086,
      by_type: { fence_intrusion: 70, distance_too_close: 26, device_alarm: 104 },
      pending: 170,
      handled: 30,
    },
  ],
};

const reportFixture = {
  summary: {
    total: 10,
    handled: 5,
    pending: 5,
    handle_rate: 0.5,
    by_type: {},
    by_level: {},
    by_handle_status: {},
    by_period: [],
  },
  items: [{ id: 1 }],
} as any;

let wrapper: ReturnType<typeof mount> | null = null;
// 桩掉重型/在 jsdom 下易出错的子组件与表格（断言不依赖其真实 DOM）。
// ElDialog 在 jsdom 下因 transition 不触发而不渲染内容，桩为按 modelValue 直渲容器。
const stubs = {
  MapPanel: true,
  DailyTrendChart: true,
  WorkPlanPopup: true,
  MediaUpload: true,
  ElTable: true,
  ElTableColumn: true,
  ElDialog: {
    props: ["modelValue"],
    template: `<div class="el-dialog-stub" v-if="modelValue"><slot /></div>`,
  },
};

beforeEach(() => {
  // jsdom 无 createObjectURL，供导出触发下载分支使用
  (globalThis as any).URL.createObjectURL = vi.fn(() => "blob:mock");
  (globalThis as any).URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.clearAllMocks();
});

describe("views/AlarmView.vue", () => {
  it("挂载即按默认拉取告警列表与趋势（onMounted 联动）", async () => {
    wrapper = mount(AlarmView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;
    // onMounted 串联拉取列表与趋势
    expect(vi.mocked(fetchAlarms)).toHaveBeenCalled();
    expect(vi.mocked(fetchAlarmTrend)).toHaveBeenCalled();
    expect(vm.trendByPeriod.length).toBeGreaterThan(0);
  });

  it("doPreviewSnapshot 拉取预览并填充 snapshotPreview，结束后 loading 复位", async () => {
    vi.mocked(fetchSnapshotPreview).mockResolvedValue(snapshotFixture);
    wrapper = mount(AlarmView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.snapshotStart = "2026-06-01";
    vm.snapshotEnd = "2026-07-01";

    expect(vm.snapshotPreviewLoading).toBe(false);
    const p = vm.doPreviewSnapshot();
    // 发起请求后同步进入 loading
    expect(vm.snapshotPreviewLoading).toBe(true);
    await p;
    expect(vm.snapshotPreviewLoading).toBe(false);
    // 预览数据为分周期结构（概览 + 各周期 + 按项目汇总），驱动预览块渲染
    expect(vm.snapshotPreview).toEqual(snapshotFixture);
    expect(vm.snapshotPreview?.periods.length).toBe(2);
    expect(vm.snapshotPreview?.project_summary.length).toBe(1);
  });

  it("doExportSnapshot 触发快照导出按钮加载中态（置位→复位）", async () => {
    vi.mocked(exportAlarmReport).mockResolvedValue(
      new Blob(["x"], { type: "application/pdf" }),
    );
    wrapper = mount(AlarmView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.snapshotStart = "2026-06-01";
    vm.snapshotEnd = "2026-07-01";

    const p = vm.doExportSnapshot("pdf");
    // 同步：导出进行中，按钮应处于 loading
    expect(vm.snapshotExporting).toBe("pdf");
    await p;
    // 结束：loading 复位
    expect(vm.snapshotExporting).toBe("");
  });

  it("openReport 打开报表弹窗并拉取填充 report，结束后 loading 复位", async () => {
    vi.mocked(fetchAlarmReport).mockResolvedValue(reportFixture);
    wrapper = mount(AlarmView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;

    const p = vm.openReport();
    expect(vm.reportLoading).toBe(true);
    await p;
    expect(vm.reportLoading).toBe(false);
    expect(vm.report).toEqual(reportFixture);
  });

  it("快照预览迷你图按类型分色堆叠渲染（每周期 3 段 + 图例）", async () => {
    wrapper = mount(AlarmView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;
    // 打开报表弹窗并填充 report（快照块在 v-if=report 内），再注入快照预览数据
    vm.report = reportFixture;
    vm.reportVisible = true;
    vm.snapshotPreview = snapshotFixture;
    await flushPromises();

    // 图例存在且含三类（红/橙/蓝 对应 围栏侵入/间距过近/设备自报）
    const legend = wrapper!.find(".mini-legend");
    expect(legend.exists()).toBe(true);
    expect(legend.text()).toContain("围栏侵入");
    expect(legend.text()).toContain("间距过近");
    expect(legend.text()).toContain("设备自报");

    // 每周期 3 段（红/橙/蓝），共 periods*3
    const segs = wrapper!.findAll(".bar-seg");
    expect(segs.length).toBe(snapshotFixture.periods.length * 3);
    // 周期标签使用 formatPeriodLabel（month → 原值）
    const labels = wrapper!.findAll(".bar-label");
    expect(labels.length).toBe(snapshotFixture.periods.length);
    expect(labels[0].text()).toBe("2026-05");
    expect(labels[1].text()).toBe("2026-06");
    // 每段均带宽度样式（与类型值正相关，非 0）
    const widths = segs.map((s) => (s.attributes("style") || ""));
    expect(widths.every((w) => /width/.test(w))).toBe(true);
  });
});
