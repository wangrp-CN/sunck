import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { ref } from "vue";
import { ElMessageBox, ElMessage } from "element-plus";

const routeState = vi.hoisted(() => ({ params: { id: "1" } as Record<string, any> }));
const push = vi.fn();
const replace = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: routeState.params, query: {} }),
  useRouter: () => ({ push, replace }),
}));

vi.mock("@/components/MapPanel.vue", () => ({
  default: {
    name: "MapPanel",
    props: ["devices", "fences", "height"],
    emits: ["device-click", "fence-click"],
    template: `<div class="map-panel-stub"></div>`,
    methods: { focusDevice() {} },
  },
}));

vi.mock("@/composables/useAlarmSound", () => ({
  useAlarmSound: () => {
    const playing = ref(false);
    return { playing, start: vi.fn(), stop: vi.fn() };
  },
  ALARM_SOUND_DURATION: 15000,
}));

const fixture = {
  project: {
    id: 1,
    name: "测试项目",
    short_name: "测项",
    start_date: "2024-01-01",
    end_date: "2024-12-31",
    section: "区间A",
    mileage: "K10+000",
    coordinate: null,
    status: "进行中",
  },
  devices: [
    {
      device_no: "TA1",
      name: "列车设备1",
      device_type: "train_approach",
      device_type_label: "列车接近",
      lng: 116.4,
      lat: 39.9,
      status: "在线",
      direction: "上行",
    },
    {
      device_no: "LOC1",
      name: "定位设备1",
      device_type: "locate",
      device_type_label: "定位",
      lng: 116.39,
      lat: 39.91,
      status: "在线",
      direction: null,
    },
  ],
  fences: [
    { id: 10, name: "围栏1", fence_type: "电子围栏", geometry_wkt: "POLYGON((0 0,1 0,1 1,0 1,0 0))", enabled: true },
  ],
  persons: [
    {
      id: 100,
      person_no: "P100",
      name: "张三",
      person_type: "施工人员",
      device_no: "LOC1",
      lng: 116.39,
      lat: 39.91,
      track_device_no: "LOC1",
    },
  ],
  machines: [
    {
      id: 200,
      machine_no: "M200",
      machine_type: "捣固车",
      spec_model: null,
      description: null,
      guard_person_name: "李四",
      lng: 116.41,
      lat: 39.92,
      track_device_no: "LOC1",
    },
  ],
  alarms: [
    { id: 1, alarm_type: "train_approach", device_type: "train_approach", device_name: "列车设备1", device_no: "TA1", alarm_level: "警告", alarm_info: "列车接近", alarm_status: "告警开始", handle_status: "待处理", fence_name: null, alarm_time: "2024-06-28 08:27:10" },
    { id: 2, alarm_type: "fence_intrusion", device_type: "anti_intrusion", device_name: "防侵1", device_no: "AI1", alarm_level: "警告", alarm_info: "围栏告警", alarm_status: "告警开始", handle_status: "待处理", fence_name: "围栏1", alarm_time: "2024-06-28 08:27:11" },
  ],
};

vi.mock("@/api/dashboard", () => ({
  getProjectDetail: vi.fn(() => Promise.resolve(JSON.parse(JSON.stringify(fixture)))),
}));
vi.mock("@/api/project", () => ({
  fetchProjects: vi.fn(() => Promise.resolve({ items: [{ id: 1, name: "测试项目" }], total: 1, page: 1, size: 1000 })),
}));
vi.mock("@/api/alarm", () => ({
  alarmTypeLabel: (t: string | null | undefined) => (t ? t : "—"),
  handleAlarm: vi.fn(() => Promise.resolve({})),
  getTrainApproachRecords: vi.fn(() => Promise.resolve([])),
  ALARM_TYPE_LABELS: {},
}));
vi.mock("element-plus", async (importOriginal: any) => {
  const mod = await importOriginal();
  return {
    ...mod,
    ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    ElMessageBox: { prompt: vi.fn(), confirm: vi.fn() },
  };
});

import ProjectDetailView from "./ProjectDetailView.vue";
import { getProjectDetail } from "@/api/dashboard";

describe("ProjectDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.params = { id: "1" };
    (getProjectDetail as any).mockResolvedValue(JSON.parse(JSON.stringify(fixture)));
    (ElMessageBox as any).prompt = vi.fn().mockResolvedValue({ value: "处置说明" });
    (ElMessageBox as any).confirm = vi.fn().mockResolvedValue(true);
    (ElMessage as any).success = vi.fn();
    push.mockClear();
    replace.mockClear();
  });

  async function mountView() {
    const wrapper = mount(ProjectDetailView, { attachTo: document.body });
    await flushPromises();
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  it("渲染项目信息栏", async () => {
    const wrapper = await mountView();
    expect(wrapper.text()).toContain("测项");
    expect(wrapper.text()).toContain("区间A");
    expect(wrapper.text()).toContain("K10+000");
  });

  it("渲染地图与告警面板（有待处理告警）", async () => {
    const wrapper = await mountView();
    expect(wrapper.find(".map-panel-stub").exists()).toBe(true);
    expect(wrapper.find(".alarm-panel").exists()).toBe(true);
    expect(wrapper.text()).toContain("列车接近");
  });

  it("人员弹窗展示字段", async () => {
    const wrapper = await mountView();
    await wrapper.findComponent({ name: "MapPanel" }).vm.$emit("device-click", { device_no: "P-100", name: "张三", device_type: "person" });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("人员姓名：");
    expect(wrapper.text()).toContain("张三");
    expect(wrapper.text()).toContain("人员类型：");
  });

  it("大机弹窗展示字段", async () => {
    const wrapper = await mountView();
    await wrapper.findComponent({ name: "MapPanel" }).vm.$emit("device-click", { device_no: "M-200", name: "M200", device_type: "machine" });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("大机名称：");
    expect(wrapper.text()).toContain("防护人员姓名：");
    expect(wrapper.text()).toContain("李四");
  });

  it("设备弹窗展示方位 + 列车接近记录入口", async () => {
    const wrapper = await mountView();
    await wrapper.findComponent({ name: "MapPanel" }).vm.$emit("device-click", { device_no: "TA1", name: "列车设备1", device_type: "train_approach" });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("设备方位：");
    expect(wrapper.text()).toContain("上行");
    expect(wrapper.text()).toContain("列车接近记录");
  });

  it("处理告警：调用 handleAlarm 并移除该行", async () => {
    const { handleAlarm } = await import("@/api/alarm");
    const wrapper = await mountView();
    const handleBtns = wrapper.findAll("button").filter((b) => b.text() === "处理");
    expect(handleBtns.length).toBeGreaterThan(0);
    await handleBtns[0].trigger("click");
    await flushPromises();
    expect((handleAlarm as any).mock.calls.length).toBe(1);
    expect((handleAlarm as any).mock.calls[0][1]).toEqual({ handle_status: "已处理", content: "处置说明" });
    // 行数减少
    const rows = wrapper.findAll(".alarm-table tbody tr");
    expect(rows.length).toBe(1);
  });

  it("忽略告警：确认后调用 handleAlarm 并移除该行", async () => {
    const { handleAlarm } = await import("@/api/alarm");
    const wrapper = await mountView();
    const ignoreBtns = wrapper.findAll("button").filter((b) => b.text() === "忽略");
    await ignoreBtns[0].trigger("click");
    await flushPromises();
    expect((handleAlarm as any).mock.calls.length).toBe(1);
    expect((handleAlarm as any).mock.calls[0][1]).toEqual({ handle_status: "已忽略" });
    expect(wrapper.findAll(".alarm-table tbody tr").length).toBe(1);
  });

  it("忽略告警：取消时不调用 handleAlarm", async () => {
    const { handleAlarm } = await import("@/api/alarm");
    (ElMessageBox as any).confirm = vi.fn().mockRejectedValue(new Error("cancel"));
    const wrapper = await mountView();
    const ignoreBtns = wrapper.findAll("button").filter((b) => b.text() === "忽略");
    await ignoreBtns[0].trigger("click");
    await flushPromises();
    expect((handleAlarm as any).mock.calls.length).toBe(0);
    expect(wrapper.findAll(".alarm-table tbody tr").length).toBe(2);
  });

  it("无待处理告警时隐藏告警面板", async () => {
    (getProjectDetail as any).mockResolvedValue({ ...JSON.parse(JSON.stringify(fixture)), alarms: [] });
    const wrapper = await mountView();
    expect(wrapper.find(".alarm-panel").exists()).toBe(false);
  });

  it("列车接近记录：打开对话框并查询", async () => {
    const { getTrainApproachRecords } = await import("@/api/alarm");
    const wrapper = await mountView();
    await wrapper.findComponent({ name: "MapPanel" }).vm.$emit("device-click", { device_no: "TA1", name: "列车设备1", device_type: "train_approach" });
    await wrapper.vm.$nextTick();
    const trainBtn = wrapper.findAll("button").find((b) => b.text() === "列车接近记录");
    expect(trainBtn).toBeTruthy();
    await trainBtn!.trigger("click");
    await flushPromises();
    expect((getTrainApproachRecords as any).mock.calls.length).toBe(1);
    expect((getTrainApproachRecords as any).mock.calls[0][0]).toEqual({ device_no: "TA1", project_id: 1 });
  });

  it("无 id 进入时默认跳转首个项目", async () => {
    routeState.params = {};
    await mountView();
    await flushPromises();
    expect(replace).toHaveBeenCalledWith({ name: "project-detail", params: { id: 1 } });
  });
});
