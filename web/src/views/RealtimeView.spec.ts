// RealtimeView 单测（实时监控：并行加载 + 实时 socket + 指令下发）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RealtimeView from "@/views/RealtimeView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElNotification: vi.fn(),
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
    longitude: 116.1,
    latitude: 39.1,
    status: "ok",
  },
];
const locations = [
  {
    device_type: "locate",
    device_no: "LOC-1",
    device_name: "定位1",
    project_id: 1,
    longitude: 116.1,
    latitude: 39.1,
    gcj02: { lng: 116.1, lat: 39.1 },
    accuracy: 1,
    speed: 0,
    status: "ok",
    report_time: "2026-07-21T10:00:00",
  },
];
const alarms = [
  {
    id: 1,
    project_id: 1,
    alarm_type: "x",
    device_type: "locate",
    device_name: "定位1",
    device_no: "LOC-1",
    alarm_info: "测试告警",
    alarm_status: "active",
    alarm_level: "警告",
    handle_status: "pending",
    handle_content: null,
    fence_name: null,
    work_plan_id: null,
    media_urls: null,
    alarm_time: "2026-07-21T10:00:00",
  },
];
const fences = { items: [{ id: 10, name: "F1", geometry_wkt: "POLYGON((0 0))" }], total: 1 };

vi.mock("@/api/realtime", () => ({
  fetchDevices: vi.fn(),
  fetchLocations: vi.fn(),
  fetchAlarms: vi.fn(),
  sendCommand: vi.fn(),
  DEVICE_ACTIONS: {
    locate: ["upload_interval", "alarm", "sound"],
    anti_intrusion: ["arm", "alarm"],
    train_approach: ["alarm"],
  },
  DEVICE_TYPE_LABELS: {
    locate: "人机定位",
    anti_intrusion: "大机防侵限",
    train_approach: "列车接近",
  },
}));
// 注意：本视图的 fetchFences 来自 @/api/fence（非 realtime），需单独 mock
vi.mock("@/api/fence", () => ({ fetchFences: vi.fn() }));
vi.mock("@/utils/ws", () => ({ createRealtimeSocket: vi.fn(() => () => {}) }));
vi.mock("@/components/MapPanel.vue", () => ({
  default: {
    name: "MapPanelStub",
    template: "<div class='map-stub'/>",
    methods: { focusDevice() {} },
  },
}));
vi.mock("@/components/WorkPlanPopup.vue", () => ({
  default: { name: "WPPStub", template: "<div class='wpp-stub'/>" },
}));

import {
  fetchDevices,
  fetchLocations,
  fetchAlarms,
  sendCommand,
} from "@/api/realtime";
import { fetchFences } from "@/api/fence";
import { createRealtimeSocket } from "@/utils/ws";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchDevices).mockResolvedValue({ items: devices, total: 1 } as any);
  vi.mocked(fetchLocations).mockResolvedValue({ items: locations, total: 1 } as any);
  vi.mocked(fetchAlarms).mockResolvedValue({ items: alarms, total: 1 } as any);
  vi.mocked(fetchFences).mockResolvedValue(fences as any);
  vi.mocked(sendCommand).mockResolvedValue({
    topic: "device/locate/LOC-1/down",
    device_type: "locate",
    device_no: "LOC-1",
    action: "alarm",
    payload: {},
  } as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/RealtimeView.vue", () => {
  it("挂载后并行加载设备/位置/告警/围栏并渲染告警列表", async () => {
    wrapper = mount(RealtimeView);
    await flushPromises();

    expect(vi.mocked(fetchDevices)).toHaveBeenCalled();
    expect(vi.mocked(fetchLocations)).toHaveBeenCalled();
    expect(vi.mocked(fetchAlarms)).toHaveBeenCalled();
    expect(vi.mocked(fetchFences)).toHaveBeenCalled();

    const vm = wrapper.vm as any;
    expect(vm.devices.length).toBe(1);
    expect(vm.alarms.length).toBe(1);
    expect(wrapper.text()).toContain("定位1");
  });

  it("建立实时 socket 并随 onStatus 更新连接态", async () => {
    let captured: any;
    vi.mocked(createRealtimeSocket).mockImplementation((_p: any, handlers: any) => {
      captured = handlers;
      return () => {};
    });
    wrapper = mount(RealtimeView);
    await flushPromises();
    expect(vi.mocked(createRealtimeSocket)).toHaveBeenCalled();
    captured.onStatus(true);
    expect((wrapper.vm as any).wsConnected).toBe(true);
  });

  it("实时位置推送写入 liveByNo 并驱动 plotPoints", async () => {
    let captured: any;
    vi.mocked(createRealtimeSocket).mockImplementation((_p: any, handlers: any) => {
      captured = handlers;
      return () => {};
    });
    wrapper = mount(RealtimeView);
    await flushPromises();
    captured.onLocation(locations[0]);
    expect((wrapper.vm as any).plotPoints.length).toBe(1);
    expect((wrapper.vm as any).plotPoints[0].live).toBe(true);
  });

  it("下发指令成功调用 sendCommand 并提示", async () => {
    wrapper = mount(RealtimeView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.cmdDeviceNo = "LOC-1";
    vm.cmdAction = "alarm";
    await vm.submitCommand();
    expect(vi.mocked(sendCommand)).toHaveBeenCalledWith(
      expect.objectContaining({ device_no: "LOC-1", action: "alarm" }),
    );
  });

  it("参数 JSON 非法时拦截不下发", async () => {
    wrapper = mount(RealtimeView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.cmdDeviceNo = "LOC-1";
    vm.cmdAction = "alarm";
    vm.cmdParams = "{bad json";
    await vm.submitCommand();
    expect(vi.mocked(sendCommand)).not.toHaveBeenCalled();
  });

  it("未选设备不下发指令", async () => {
    wrapper = mount(RealtimeView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.cmdDeviceNo = "";
    vm.cmdAction = "";
    await vm.submitCommand();
    expect(vi.mocked(sendCommand)).not.toHaveBeenCalled();
  });
});
