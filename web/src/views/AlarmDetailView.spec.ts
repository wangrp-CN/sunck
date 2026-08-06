import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { ElMessage } from "element-plus";

const routeState = vi.hoisted(() => ({ params: {} as Record<string, any> }));
const push = vi.fn();
const replace = vi.fn();
const back = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: routeState.params, query: {}, path: "/alarms/1/detail" }),
  useRouter: () => ({ push, replace, back }),
}));

// MapPanel 依赖高德 SDK + DOM，必须 stub；保留 focusDevice 供组件可选链调用
vi.mock("@/components/MapPanel.vue", () => ({
  default: {
    name: "MapPanel",
    props: ["devices", "fences", "height"],
    template: `<div class="map-panel-stub"></div>`,
    methods: { focusDevice() {} },
  },
}));

// 变体A：围栏告警（含围栏名称，无媒体）
const fenceAlarm = {
  id: 1,
  project_id: 9,
  project_name: "京广高铁改造项目",
  alarm_type: "fence_intrusion",
  device_type: "locate",
  device_name: "安全帽A",
  device_no: "AD-001",
  alarm_info: "人员（张三）进入围栏（1号围栏）触发告警",
  alarm_status: "告警开始",
  alarm_level: "警告",
  handle_status: "待处理",
  handle_content: null,
  fence_name: "1号围栏",
  work_plan_id: null,
  media_urls: [],
  alarm_time: "2024-06-28T08:27:10+08:00",
  hazard_id: null,
  created_at: "2024-06-28T08:27:11+08:00",
};

// 变体B：大机防侵限告警（无围栏名称，含图片 + 视频）
const machineAlarm = {
  ...fenceAlarm,
  id: 2,
  alarm_type: "device_alarm",
  fence_name: null,
  media_urls: ["alarms/2/shot.jpg", "alarms/2/clip.mp4"],
};

vi.mock("@/api/alarm", () => ({
  getAlarmDetail: vi.fn(),
  getLatestAlarm: vi.fn(() => Promise.resolve({ id: 7 })),
  handleAlarm: vi.fn(() => Promise.resolve({})),
  alarmTypeLabel: (t: string | null | undefined) =>
    ({ fence_intrusion: "围栏侵入", device_alarm: "设备告警" })[t as string] || "—",
  ALARM_TYPE_LABELS: {},
}));
vi.mock("@/api/realtime", () => ({
  fetchLocations: vi.fn(() =>
    Promise.resolve({
      total: 1,
      items: [
        {
          device_type: "locate",
          device_no: "AD-001",
          device_name: "安全帽A",
          project_id: 9,
          longitude: 116.39,
          latitude: 39.9,
          gcj02: { lng: 116.4, lat: 39.91 },
          accuracy: null,
          speed: null,
          status: "在线",
          report_time: null,
        },
      ],
    }),
  ),
}));
vi.mock("@/api/fence", () => ({
  fetchFences: vi.fn(() =>
    Promise.resolve({
      items: [{ id: 3, name: "1号围栏", geometry_wkt: "POLYGON((0 0,1 0,1 1,0 0))" }],
      total: 1,
      page: 1,
      size: 20,
    }),
  ),
}));
vi.mock("@/utils/media", () => ({
  mediaKeyFromUrl: (u: string) => u,
  resolvePresigned: vi.fn((keys: string[]) =>
    Promise.resolve(Object.fromEntries(keys.map((k) => [k, `https://signed/${k}`]))),
  ),
}));
vi.mock("element-plus", async (importOriginal: any) => {
  const mod = await importOriginal();
  return {
    ...mod,
    ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  };
});

import AlarmDetailView from "./AlarmDetailView.vue";
import { getAlarmDetail, getLatestAlarm, handleAlarm } from "@/api/alarm";

const clone = (o: any) => JSON.parse(JSON.stringify(o));

describe("AlarmDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.params = { id: "1" };
    (getAlarmDetail as any).mockResolvedValue(clone(fenceAlarm));
    (getLatestAlarm as any).mockResolvedValue({ id: 7 });
    (handleAlarm as any).mockResolvedValue({});
    (ElMessage as any).success = vi.fn();
    (ElMessage as any).error = vi.fn();
    (ElMessage as any).warning = vi.fn();
    push.mockClear();
    replace.mockClear();
    back.mockClear();
  });

  async function mountView() {
    const wrapper = mount(AlarmDetailView, {
      attachTo: document.body,
      global: { directives: { loading: {} } },
    });
    await flushPromises();
    await wrapper.vm.$nextTick();
    return wrapper;
  }

  it("渲染原型骨架：只读字段与处理/取消按钮", async () => {
    const wrapper = await mountView();
    const text = wrapper.text();
    expect(text).toContain("项目名称：");
    expect(text).toContain("告警类型：");
    expect(text).toContain("告警信息：");
    expect(text).toContain("告警时间：");
    expect(text).toContain("处理内容：");
    const btns = wrapper.findAll("button").map((b) => b.text());
    expect(btns).toContain("处理");
    expect(btns).toContain("取消");
  });

  it("变体A（围栏告警）：展示围栏名称，不展示告警图片/视频行", async () => {
    const wrapper = await mountView();
    const text = wrapper.text();
    expect(text).toContain("围栏名称：");
    expect(text).not.toContain("告警图片：");
    expect(text).not.toContain("告警视频：");
  });

  it("变体B（含媒体）：展示告警图片/告警视频行，隐藏围栏名称", async () => {
    (getAlarmDetail as any).mockResolvedValue(clone(machineAlarm));
    const wrapper = await mountView();
    const text = wrapper.text();
    expect(text).toContain("告警图片：");
    expect(text).toContain("告警视频：");
    expect(text).not.toContain("围栏名称：");
    // 蓝色下划线链接「图片」「视频」
    const links = wrapper.findAll(".ad-media-link").map((a) => a.text());
    expect(links).toEqual(["图片", "视频"]);
  });

  it("只读字段取值正确（项目名称直接取详情端点的 project_name）", async () => {
    const wrapper = await mountView();
    const values = wrapper.findAll("input").map((i) => (i.element as HTMLInputElement).value);
    expect(values).toContain("京广高铁改造项目");
    expect(values).toContain("围栏侵入");
    expect(values).toContain("1号围栏");
    expect(values).toContain("人员（张三）进入围栏（1号围栏）触发告警");
    // 告警时间格式化为原型样式 YYYY-MM-DD HH:mm:ss
    expect(values.some((v) => /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(v))).toBe(true);
  });

  it("点击「图片」链接打开媒体弹窗", async () => {
    (getAlarmDetail as any).mockResolvedValue(clone(machineAlarm));
    const wrapper = await mountView();
    expect((wrapper.vm as any).mediaDialog).toBe(false);
    await wrapper.findAll(".ad-media-link")[0].trigger("click");
    await flushPromises();
    expect((wrapper.vm as any).mediaDialog).toBe(true);
    expect((wrapper.vm as any).mediaDialogKind).toBe("image");
  });

  it("处理：提交 已消警（触发后端下发消警指令）并返回原页面", async () => {
    const wrapper = await mountView();
    (wrapper.vm as any).handleContent = "现场已核实并处置";
    await wrapper.vm.$nextTick();
    const handleBtn = wrapper.findAll("button").find((b) => b.text() === "处理")!;
    await handleBtn.trigger("click");
    await flushPromises();
    expect((handleAlarm as any).mock.calls[0][0]).toBe(1);
    expect((handleAlarm as any).mock.calls[0][1]).toEqual({
      handle_status: "已消警",
      content: "现场已核实并处置",
    });
    expect((ElMessage as any).success).toHaveBeenCalled();
  });

  it("取消：返回原页面，不调用处置接口", async () => {
    const wrapper = await mountView();
    const cancelBtn = wrapper.findAll("button").find((b) => b.text() === "取消")!;
    await cancelBtn.trigger("click");
    await flushPromises();
    expect(handleAlarm).not.toHaveBeenCalled();
    expect(back.mock.calls.length + push.mock.calls.length).toBeGreaterThan(0);
  });

  it("已处理的告警：处理按钮禁用，不可重复处置", async () => {
    (getAlarmDetail as any).mockResolvedValue({
      ...clone(fenceAlarm),
      handle_status: "已处理",
      handle_content: "已处置",
    });
    const wrapper = await mountView();
    const handleBtn = wrapper.findAll("button").find((b) => b.text() === "处理")!;
    expect(handleBtn.attributes("disabled")).toBeDefined();
  });

  it("无 id 入口：定位最新告警并 replace 到带 id 路由", async () => {
    routeState.params = {};
    await mountView();
    expect(getLatestAlarm).toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith({
      name: "alarm-detail",
      params: { id: "7" },
    });
  });

  it("无 id 入口且无任何告警：提示暂无告警记录", async () => {
    routeState.params = {};
    (getLatestAlarm as any).mockResolvedValue(null);
    await mountView();
    expect(replace).not.toHaveBeenCalled();
    expect((ElMessage as any).warning).toHaveBeenCalledWith("暂无告警记录");
  });

  it("地图：定位到告警设备并绘制关联围栏", async () => {
    const wrapper = await mountView();
    const map = wrapper.findComponent({ name: "MapPanel" });
    expect(map.exists()).toBe(true);
    expect(map.props("devices")).toHaveLength(1);
    expect((map.props("devices") as any[])[0].device_no).toBe("AD-001");
    expect(map.props("fences")).toHaveLength(1);
    // 红色高亮框（原型 3px #D9001B）
    expect(wrapper.find(".ad-map-highlight").exists()).toBe(true);
  });

  it("设备无定位数据时展示占位提示而非红框", async () => {
    const { fetchLocations } = await import("@/api/realtime");
    (fetchLocations as any).mockResolvedValue({ total: 0, items: [] });
    const wrapper = await mountView();
    expect(wrapper.find(".ad-map-highlight").exists()).toBe(false);
    expect(wrapper.find(".ad-map-empty").exists()).toBe(true);
  });
});
