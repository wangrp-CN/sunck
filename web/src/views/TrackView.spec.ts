// TrackView 单测（轨迹回放：设备加载/查询解析/逐帧跳转/预设时间）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TrackView from "@/views/TrackView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

const devices = [
  {
    device_type: "locate",
    device_type_label: "人机定位",
    device_id: 1,
    device_no: "LOC-1",
    name: "定位1",
    project_id: 1,
    longitude: 1,
    latitude: 1,
    status: "ok",
  },
];
const traj = {
  items: [
    {
      device_no: "LOC-1",
      gcj02: { lng: 116.1, lat: 39.1 },
      longitude: 116.0,
      latitude: 39.0,
      speed: 10,
      status: "ok",
      report_time: "2026-07-21T10:00:00",
    },
    {
      device_no: "LOC-1",
      gcj02: { lng: 116.2, lat: 39.2 },
      longitude: 116.1,
      latitude: 39.1,
      speed: 12,
      status: "ok",
      report_time: "2026-07-21T10:00:05",
    },
  ],
  total: 2,
};

vi.mock("@/api/realtime", () => ({
  fetchDevices: vi.fn(),
  fetchTrajectory: vi.fn(),
  DEVICE_TYPE_LABELS: {
    locate: "人机定位",
    anti_intrusion: "大机防侵限",
    train_approach: "列车接近",
  },
}));
vi.mock("@/components/MapPanel.vue", () => ({
  default: {
    name: "MapPanelStub",
    template: "<div class='map-stub'/>",
    methods: {
      setTrajectory() {},
      setMovingMarker() {},
      removeMovingMarker() {},
      clearTrajectory() {},
    },
  },
}));

import { fetchDevices, fetchTrajectory } from "@/api/realtime";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchDevices).mockResolvedValue({ items: devices, total: 1 } as any);
  vi.mocked(fetchTrajectory).mockResolvedValue(traj as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

const RANGE: [Date, Date] = [
  new Date("2026-07-21T09:00:00Z"),
  new Date("2026-07-21T11:00:00Z"),
];

describe("views/TrackView.vue", () => {
  it("挂载后加载设备列表并预设近24h时间范围", async () => {
    wrapper = mount(TrackView);
    await flushPromises();
    expect(vi.mocked(fetchDevices)).toHaveBeenCalled();
    const vm = wrapper.vm as any;
    expect(vm.devices.length).toBe(1);
    expect(vm.timeRange).not.toBeNull();
  });

  it("查询轨迹：解析坐标/时间并渲染点列表", async () => {
    wrapper = mount(TrackView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.deviceNo = "LOC-1";
    vm.timeRange = RANGE;
    await vm.query();
    await flushPromises();
    expect(vi.mocked(fetchTrajectory)).toHaveBeenCalled();
    expect(vm.points.length).toBe(2);
    expect(vm.coords.length).toBe(2);
    expect(vm.times.length).toBe(2);
    expect(vm.durationMs).toBe(5000);
  });

  it("未选设备查询被拦截", async () => {
    wrapper = mount(TrackView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.deviceNo = "";
    await vm.query();
    expect(vi.mocked(fetchTrajectory)).not.toHaveBeenCalled();
  });

  it("点击表格行跳转至该轨迹点（progress 跳到 100%）", async () => {
    wrapper = mount(TrackView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.deviceNo = "LOC-1";
    vm.timeRange = RANGE;
    await vm.query();
    await flushPromises();
    const row = vm.points[1];
    vm.onRowClick(row);
    // 末帧跳转：playMs=duration → progress=100，currentTime 被刷新为末点时间
    expect(vm.progress).toBe(100);
    expect(vm.currentTime).toBeTruthy();
  });

  it("setPreset 切换时间范围跨度", async () => {
    wrapper = mount(TrackView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.setPreset(1);
    const span = (vm.timeRange[1].getTime() - vm.timeRange[0].getTime()) / 3600000;
    expect(span).toBeCloseTo(1, 0);
  });
});
