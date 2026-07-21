// DeviceOnlineView 单测（在线看板：拉取在线状态 + 概览/明细/按类型）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DeviceOnlineView from "@/views/DeviceOnlineView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

const onlineResult = {
  threshold_seconds: 300,
  total: 3,
  online: 2,
  offline: 1,
  by_type: {
    locate: { total: 2, online: 2, offline: 0 },
    anti_intrusion: { total: 1, online: 0, offline: 1 },
  },
  items: [
    {
      device_type: "locate",
      device_no: "LOC-1",
      device_name: "定位1",
      project_id: 1,
      longitude: 116.1,
      latitude: 39.1,
      gcj02: { lng: 116.1, lat: 39.1 },
      status: "ok",
      report_time: "2026-07-21T10:00:00",
      online: true,
      age_seconds: 10,
    },
    {
      device_type: "locate",
      device_no: "LOC-2",
      device_name: "定位2",
      project_id: 1,
      longitude: 116.2,
      latitude: 39.2,
      gcj02: { lng: 116.2, lat: 39.2 },
      status: "ok",
      report_time: "2026-07-21T10:00:00",
      online: true,
      age_seconds: 20,
    },
    {
      device_type: "anti_intrusion",
      device_no: "AI-1",
      device_name: "大机1",
      project_id: 2,
      longitude: 116.3,
      latitude: 39.3,
      gcj02: null,
      status: "ok",
      report_time: "2026-07-21T09:00:00",
      online: false,
      age_seconds: 400,
    },
  ],
};

vi.mock("@/api/realtime", () => ({
  fetchOnlineStatus: vi.fn(),
  DEVICE_TYPE_LABELS: {
    locate: "人机定位",
    anti_intrusion: "大机防侵限",
    train_approach: "列车接近",
  },
}));
// 注意：本视图的 fetchProjects 来自 @/api/project（非 realtime），需单独 mock
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("@/components/MapPanel.vue", () => ({
  default: { name: "MapPanelStub", template: "<div class='map-stub'/>" },
}));

import { fetchOnlineStatus } from "@/api/realtime";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchOnlineStatus).mockResolvedValue(onlineResult as any);
  // 单次返回即可（loadProjects 循环在 all.length >= total 时 break）
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [
      { id: 1, name: "项目A" },
      { id: 2, name: "项目B" },
    ],
    total: 2,
  } as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/DeviceOnlineView.vue", () => {
  it("挂载后拉取在线状态 + 项目，并渲染概览与明细", async () => {
    wrapper = mount(DeviceOnlineView);
    await flushPromises();

    expect(vi.mocked(fetchOnlineStatus)).toHaveBeenCalled();
    expect(vi.mocked(fetchProjects)).toHaveBeenCalled();
    const vm = wrapper.vm as any;
    expect(vm.summary.total).toBe(3);
    expect(vm.summary.online).toBe(2);
    expect(vm.summary.offline).toBe(1);
    expect(vm.summary.threshold).toBe(300);
    expect(vm.items.length).toBe(3);
    expect(vm.byTypeList.length).toBe(2);
    // 明细表含项目名称映射
    expect(wrapper.text()).toContain("项目A");
  });

  it("在线率计算正确（2/3 ≈ 67%）", async () => {
    wrapper = mount(DeviceOnlineView);
    await flushPromises();
    expect((wrapper.vm as any).summary.rate).toBe(67);
    expect(wrapper.text()).toContain("67%");
  });

  it("地图打点仅取带 gcj02 的设备", async () => {
    wrapper = mount(DeviceOnlineView);
    await flushPromises();
    // 3 个设备里 AI-1 的 gcj02 为 null → 仅 2 个点
    expect((wrapper.vm as any).mapDevices.length).toBe(2);
  });

  it("fmtAge 时间格式化", async () => {
    wrapper = mount(DeviceOnlineView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vm.fmtAge(45)).toBe("45s");
    expect(vm.fmtAge(125)).toBe("2m5s");
    expect(vm.fmtAge(null)).toBe("—");
  });
});
