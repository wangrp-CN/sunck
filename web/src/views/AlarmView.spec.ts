// AlarmView 单测（告警管理：加载列表/地图、媒体 presigned 解析、筛选、处置、权限）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Alarm } from "@/types";
import AlarmView from "@/views/AlarmView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElNotification: vi.fn(),
    ElMessageBox: { confirm: vi.fn() },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: { permission_codes: ["alarm:handle", "alarm:config", "alarm:list"] },
    loadProfile: vi.fn(),
  })),
}));

// AlarmView 现使用 useRouter（转隐患成功跳转），测试无 router 插件，桩掉避免告警
vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/", meta: {} }),
}));

const alarms = {
  items: [
    {
      id: 1,
      project_id: 1,
      alarm_type: "fence_intrusion",
      device_type: "locate",
      device_name: "定位1",
      device_no: "LOC-1",
      alarm_info: "侵入",
      alarm_status: "告警开始",
      alarm_level: "警告",
      handle_status: "待处理",
      handle_content: null,
      fence_name: null,
      work_plan_id: null,
      media_urls: ["/api/v1/media/key/a1.png"],
      alarm_time: "2026-07-21T10:00:00",
    },
    {
      id: 2,
      project_id: 1,
      alarm_type: "device_alarm",
      device_type: "anti_intrusion",
      device_name: "大机1",
      device_no: "AI-1",
      alarm_info: "越限",
      alarm_status: "已消警",
      alarm_level: "严重",
      handle_status: "已处理",
      handle_content: "已处置",
      fence_name: null,
      work_plan_id: null,
      media_urls: null,
      alarm_time: "2026-07-21T09:00:00",
    },
  ],
  total: 2,
};

vi.mock("@/api/realtime", () => ({
  fetchAlarms: vi.fn(),
  fetchDevices: vi.fn(),
  fetchLocations: vi.fn(),
  DEVICE_TYPE_LABELS: { locate: "人机定位", anti_intrusion: "大机防侵限", train_approach: "列车接近" },
}));
vi.mock("@/api/fence", () => ({ fetchFences: vi.fn() }));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("@/api/person", () => ({ fetchPersons: vi.fn() }));
vi.mock("@/api/media", () => ({ putAlarmMedia: vi.fn() }));
vi.mock("@/api/alarm", () => ({
  convertAlarmToHazard: vi.fn(),
  exportAlarmReport: vi.fn(),
  fetchAlarmPeriod: vi.fn(),
  fetchAlarmReport: vi.fn(),
  fetchAlarmTrend: vi.fn(),
  fetchSnapshotPreview: vi.fn(),
  getAlarmConfig: vi.fn(),
  handleAlarm: vi.fn(),
  updateAlarmConfig: vi.fn(),
}));
// 保留 mediaKeyFromUrl 真实逻辑，仅替换resolvePresigned（命中网络）
vi.mock("@/utils/media", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, resolvePresigned: vi.fn() };
});
vi.mock("@/components/MapPanel.vue", () => ({ default: { name: "M", template: "<div/>", methods: { focusDevice() {} } } }));
vi.mock("@/components/DailyTrendChart.vue", () => ({ default: { name: "DTC", template: "<div/>" } }));
vi.mock("@/components/WorkPlanPopup.vue", () => ({ default: { name: "WPP", template: "<div/>" } }));
vi.mock("@/components/MediaUpload.vue", () => ({ default: { name: "MU", template: "<div/>" } }));

import { fetchAlarms } from "@/api/realtime";
import { handleAlarm } from "@/api/alarm";
import { putAlarmMedia } from "@/api/media";
import { resolvePresigned } from "@/utils/media";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchAlarms).mockResolvedValue(alarms as any);
  vi.mocked(putAlarmMedia).mockResolvedValue({ id: 1, media_urls: [] });
  vi.mocked(handleAlarm).mockResolvedValue({ id: 1 } as Alarm);
  vi.mocked(resolvePresigned).mockImplementation(async (keys: string[]) =>
    Object.fromEntries(keys.map((k) => [k, `https://minio/${k}`])),
  );
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/AlarmView.vue", () => {
  it("挂载后加载项目/告警/地图/趋势", async () => {
    wrapper = mount(AlarmView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vi.mocked(fetchAlarms)).toHaveBeenCalled();
    expect(vm.list.length).toBe(2);
    expect(vm.total).toBe(2);
  });

  it("媒体代理 URL → 部门隔离预签名直连（守护 #10）", async () => {
    wrapper = mount(AlarmView);
    await flushPromises();
    const vm = wrapper.vm as any;
    // 列表含 /api/v1/media/key/a1.png → mediaKeyFromUrl 提 key → resolvePresigned 回显
    expect(vi.mocked(resolvePresigned)).toHaveBeenCalled();
    const src = vm.mediaSrc["/api/v1/media/key/a1.png"];
    expect(src).toBe("https://minio/key/a1.png");
  });

  it("应用筛选：回到第1页并带条件重载", async () => {
    wrapper = mount(AlarmView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.page = 3;
    vm.filters.handle_status = "待处理";
    await vm.applyFilters();
    await flushPromises();
    expect(vm.page).toBe(1);
    expect(vi.mocked(fetchAlarms)).toHaveBeenLastCalledWith(
      expect.objectContaining({ handle_status: "待处理", page: 1 }),
    );
  });

  it("处置弹窗提交调用 handleAlarm 并刷新列表", async () => {
    wrapper = mount(AlarmView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openHandle(vm.list[0]);
    vm.handleForm.content = "已现场处置";
    await vm.submitHandle();
    await flushPromises();
    expect(vi.mocked(handleAlarm)).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ handle_status: "已处理", content: "已现场处置" }),
    );
  });

  it("权限：alarm:handle 命中时 canHandle 为 true", async () => {
    wrapper = mount(AlarmView);
    await flushPromises();
    expect((wrapper.vm as any).canHandle).toBe(true);
  });
});
