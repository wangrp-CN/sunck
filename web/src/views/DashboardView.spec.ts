import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DashboardView from "@/views/DashboardView.vue";
import { fetchSnapshotPreview, exportAlarmReport } from "@/api/alarm";
import { previewToTSV } from "@/utils/snapshot";
import type { SnapshotPreviewResult } from "@/api/alarm";

// 仅替换 ElMessage，保留 element-plus 其余组件导出
vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});
vi.mock("@/api/dashboard", () => ({
  getDashboardStats: vi.fn().mockResolvedValue({
    projects: 1,
    devices: 3,
    alarms_today: 0,
    alarms_unhandled: 0,
    device_by_type: [],
  }),
  getRecentAlarms: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/api/realtime", () => ({
  fetchLocations: vi.fn().mockResolvedValue({ items: [] }),
  fetchDevices: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/api/fence", () => ({
  fetchFences: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("@/api/alarm", () => ({
  fetchSnapshotPreview: vi.fn(),
  exportAlarmReport: vi.fn(),
}));

const fixture: SnapshotPreviewResult = {
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

let wrapper: ReturnType<typeof mount> | null = null;
// 桩掉重型/在 jsdom 下易出错的子组件与表格（断言不依赖其真实 DOM）。
// ElDialog 在 jsdom 下因 transition 不触发而不渲染内容，桩为按 modelValue 直渲容器。
const stubs = {
  MapPanel: true,
  WorkPlanPopup: true,
  ElTable: true,
  ElTableColumn: true,
  ElDialog: {
    props: ["modelValue"],
    template: `<div class="el-dialog-stub" v-if="modelValue"><slot /></div>`,
  },
};

beforeEach(() => {
  // 提供 clipboard，使复制走 clipboard API 分支
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.clearAllMocks();
});

describe("views/DashboardView.vue", () => {
  it("挂载即按默认范围拉取仪表盘统计（onMounted 联动）", async () => {
    const { getDashboardStats } = await import("@/api/dashboard");
    wrapper = mount(DashboardView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(getDashboardStats).toHaveBeenCalled();
    expect(vm.trendRange).toBeTruthy(); // 默认范围已设置
  });

  it("openSnapshotPreview 拉取预览并填充 snapPreview，结束后 loading 复位", async () => {
    vi.mocked(fetchSnapshotPreview).mockResolvedValue(fixture);
    wrapper = mount(DashboardView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;

    expect(vm.snapPreviewLoading).toBe(false);
    const p = vm.openSnapshotPreview();
    // 发起请求后同步进入 loading
    expect(vm.snapPreviewLoading).toBe(true);
    await p;
    expect(vm.snapPreviewLoading).toBe(false);
    expect(vm.snapPreview).toEqual(fixture);

    // 预览弹层打开后，迷你趋势图按类型分色堆叠渲染：每周期 3 段（红/橙/蓝），共 periods*3
    await flushPromises();
    const segs = wrapper!.findAll(".bar-seg");
    expect(segs.length).toBe(fixture.periods.length * 3);
    const legend = wrapper!.find(".mini-legend");
    expect(legend.exists()).toBe(true);
    expect(legend.text()).toContain("围栏侵入");
  });

  it("exportFromPreview 触发导出按钮加载中态（置位→复位）", async () => {
    vi.mocked(exportAlarmReport).mockResolvedValue(
      new Blob(["pdf"], { type: "application/pdf" }),
    );
    wrapper = mount(DashboardView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;

    const p = vm.exportFromPreview("pdf");
    // 同步：导出进行中，按钮应处于 loading
    expect(vm.snapPreviewExporting).toBe("pdf");
    await p;
    // 结束：loading 复位
    expect(vm.snapPreviewExporting).toBe("");
  });

  it("copyPreviewAsTable 把预览结果以 TSV 写入剪贴板", async () => {
    wrapper = mount(DashboardView, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.snapPreview = fixture;
    await vm.copyPreviewAsTable();

    const writeText = navigator.clipboard.writeText as any;
    expect(writeText).toHaveBeenCalledTimes(1);
    const written = writeText.mock.calls[0][0] as string;
    expect(written).toBe(previewToTSV(fixture));
    expect(written).toContain("2026-05\t109\t40\t0\t69\t80\t29"); // 稀疏类型补 0
  });
});
