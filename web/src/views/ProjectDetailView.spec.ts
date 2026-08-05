// ProjectDetailView 单测（大屏·项目详情页）
// 覆盖原型要求：信息栏省略+tooltip / 四类详情弹窗 / 告警面板（处理跳详情、忽略二次确认、
// 无告警不显示）/ 新告警声光提醒 / 列车接近记录带条件跳转。
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectDetailView from "@/views/ProjectDetailView.vue";

const hoist = vi.hoisted(() => {
  const push = vi.fn();
  const confirm = vi.fn().mockResolvedValue("confirm");
  const makeDetail = () => ({
    project: {
      id: 1,
      name: "P项目",
      short_name: "P",
      start_date: "2026-01-01",
      end_date: "2026-06-01",
      section: "K1~K2",
      mileage: "3km",
      coordinate: "116.4,39.9",
      status: "在建",
    },
    devices: [
      {
        device_no: "D1",
        name: "设备1",
        device_type: "anti_intrusion",
        device_type_label: "大机防侵限",
        lng: 116.4,
        lat: 39.9,
        status: "在线",
        live: true,
        direction: null,
        report_time: null,
      },
      {
        device_no: "T1",
        name: "列车接近设备1",
        device_type: "train_approach",
        device_type_label: "列车接近告警",
        lng: 116.41,
        lat: 39.91,
        status: "在线",
        live: false,
        direction: "上行",
        report_time: null,
      },
    ],
    fences: [
      {
        id: 1,
        name: "F1",
        fence_type: "电子围栏",
        geometry_wkt: "POLYGON((0 0,0 1,1 1,1 0,0 0))",
        enabled: true,
      },
    ],
    persons: [{ id: 1, person_no: "PN1", name: "张三", person_type: "防护", device_no: "D1" }],
    machines: [
      {
        id: 1,
        machine_no: "M1",
        machine_type: "捣固车",
        spec_model: "X1",
        description: "大机1",
        guard_person_name: "张三",
        lng: 116.4,
        lat: 39.9,
        track_device_no: "D1",
      },
    ],
    alarms: [
      {
        id: 1,
        alarm_type: "fence_intrusion",
        device_type: null,
        device_name: null,
        device_no: null,
        alarm_level: "严重",
        alarm_info: "机械（M1）进入围栏（F1）触发报警",
        alarm_status: "active",
        handle_status: "待处理",
        fence_name: "F1",
        alarm_time: "2026-06-28T08:27:10",
      },
    ],
  });
  return { push, confirm, makeDetail };
});

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: hoist.confirm },
  };
});

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: hoist.push, resolve: () => ({ href: "/track" }) }),
  useRoute: () => ({ params: { id: "1" }, query: {}, path: "/projects/1/detail", meta: {} }),
}));

vi.mock("@/api/dashboard", () => ({
  getProjectDetail: vi.fn().mockImplementation(() => Promise.resolve(hoist.makeDetail())),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: vi
    .fn()
    .mockResolvedValue({ items: [{ id: 1, name: "P项目" }], total: 1, page: 1, size: 200 }),
}));

vi.mock("@/api/alarm", () => ({
  handleAlarm: vi.fn().mockResolvedValue({}),
  alarmTypeLabel: (t: string | null) =>
    ({ fence_intrusion: "围栏侵入", train_approach: "列车接近预警" })[t || ""] || t || "—",
}));

vi.mock("@/components/MapPanel.vue", () => ({
  default: {
    name: "MapPanel",
    template: "<div class='map-mock'></div>",
    methods: { focusDevice() {} },
  },
}));

const loadingStub = { directives: { loading: { mounted() {}, updated() {} } } };

function mountView() {
  return mount(ProjectDetailView, { global: loadingStub });
}

function btnByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text));
}

type Vm = {
  searchType: string;
  searchEntityId: number | string | null;
  load: () => Promise<void>;
  soundPlaying: boolean;
  alarmPanelCollapsed: boolean;
  hasAlarms: boolean;
  stopAlarmSound: () => void;
  viewTrainRecords: (no: string) => void;
};

describe("ProjectDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoist.confirm.mockResolvedValue("confirm");
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  it("渲染项目信息栏、搜索区与告警面板（含 处理/忽略）", async () => {
    const wrapper = mountView();
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("项目简称：");
    expect(text).toContain("开工日期：");
    expect(text).toContain("完工日期：");
    expect(text).toContain("区间：");
    expect(text).toContain("里程：");
    expect(text).toContain("搜索方式：");
    expect(text).toContain("告警信息");
    expect(text).toContain("告警类型");
    expect(text).toContain("处理");
    expect(text).toContain("忽略");
    // 告警类型按字典转中文
    expect(text).toContain("围栏侵入");
  });

  it("项目信息值使用省略样式，便于超长内容截断后 hover 展示", async () => {
    const wrapper = mountView();
    await flushPromises();
    const values = wrapper.findAll(".info-value");
    expect(values.length).toBe(5);
    expect(values[0].text()).toBe("P");
  });

  it("搜索大机弹出详情：含防护人员姓名/坐标/大机类型，查看轨迹可点击", async () => {
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as Vm;
    vm.searchType = "machine";
    vm.searchEntityId = 1;
    await flushPromises();

    await btnByText(wrapper, "搜索")!.trigger("click");
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("大机名称：");
    expect(text).toContain("大机编号：");
    expect(text).toContain("防护人员姓名：张三");
    expect(text).toContain("坐标：116.400000，39.900000");
    expect(text).toContain("大机类型：捣固车");
    const trackBtn = btnByText(wrapper, "查看轨迹")!;
    expect(trackBtn.attributes("disabled")).toBeUndefined();
  });

  it("搜索人员弹出详情：含人员姓名/编号/设备/坐标 + 查看轨迹", async () => {
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as Vm;
    vm.searchType = "person";
    vm.searchEntityId = 1;
    await flushPromises();

    await btnByText(wrapper, "搜索")!.trigger("click");
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("人员姓名：张三");
    expect(text).toContain("人员编号：PN1");
    expect(text).toContain("设备名称：设备1");
    expect(text).toContain("设备编号：D1");
    expect(text).toContain("人员类型：防护");
    expect(text).toContain("坐标：116.400000，39.900000");
  });

  it("搜索围栏弹出详情：围栏名称/编号/类型", async () => {
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as Vm;
    vm.searchType = "fence";
    vm.searchEntityId = 1;
    await flushPromises();

    await btnByText(wrapper, "搜索")!.trigger("click");
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("围栏名称：F1");
    expect(text).toContain("围栏编号：1");
    expect(text).toContain("围栏类型：电子围栏");
  });

  it("列车接近设备弹窗展示真实设备方位，并可跳转列车接近记录", async () => {
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as Vm;
    vm.searchType = "device";
    vm.searchEntityId = "T1";
    await flushPromises();

    await btnByText(wrapper, "搜索")!.trigger("click");
    await flushPromises();

    // 方位取后端 direction，而非硬编码
    expect(wrapper.text()).toContain("设备方位：上行");

    await btnByText(wrapper, "列车接近记录")!.trigger("click");
    expect(hoist.push).toHaveBeenCalledWith({
      name: "alarms",
      query: { device_no: "T1", alarm_type: "train_approach", project_id: "1" },
    });
  });

  it("「处理」跳转告警详情页而非就地处置", async () => {
    const wrapper = mountView();
    await flushPromises();
    const handleMock = (await import("@/api/alarm")).handleAlarm as ReturnType<typeof vi.fn>;
    handleMock.mockClear();

    await btnByText(wrapper, "处理")!.trigger("click");
    await flushPromises();

    expect(handleMock).not.toHaveBeenCalled();
    expect(hoist.push).toHaveBeenCalledWith({
      name: "alarms",
      query: { alarm_id: "1", project_id: "1", alarm_type: "fence_intrusion" },
    });
  });

  it("「忽略」需二次确认，确认后调用 handleAlarm 并从列表移除", async () => {
    const wrapper = mountView();
    await flushPromises();
    const handleMock = (await import("@/api/alarm")).handleAlarm as ReturnType<typeof vi.fn>;
    handleMock.mockClear();

    await btnByText(wrapper, "忽略")!.trigger("click");
    await flushPromises();

    // 二次确认文案与原型一致
    expect(hoist.confirm).toHaveBeenCalledTimes(1);
    expect(hoist.confirm.mock.calls[0][0]).toBe("您确认忽略当前告警？");
    expect(handleMock).toHaveBeenCalledWith(1, { handle_status: "已忽略" });
    // 列表已空 → 面板整体不再渲染
    expect((wrapper.vm as unknown as Vm).hasAlarms).toBe(false);
    expect(wrapper.find(".alarm-panel").exists()).toBe(false);
  });

  it("取消二次确认时不调用处置接口", async () => {
    hoist.confirm.mockRejectedValueOnce(new Error("cancel"));
    const wrapper = mountView();
    await flushPromises();
    const handleMock = (await import("@/api/alarm")).handleAlarm as ReturnType<typeof vi.fn>;
    handleMock.mockClear();

    await btnByText(wrapper, "忽略")!.trigger("click");
    await flushPromises();

    expect(handleMock).not.toHaveBeenCalled();
    expect((wrapper.vm as unknown as Vm).hasAlarms).toBe(true);
  });

  it("无待处理告警时，告警面板与折叠条均不渲染", async () => {
    const { getProjectDetail } = await import("@/api/dashboard");
    const empty = hoist.makeDetail();
    empty.alarms = [];
    (getProjectDetail as ReturnType<typeof vi.fn>).mockResolvedValueOnce(empty);

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find(".alarm-panel").exists()).toBe(false);
    expect(wrapper.find(".alarm-panel-collapsed").exists()).toBe(false);
  });

  it("轮询发现新告警时展开面板并触发报警声", async () => {
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as Vm;
    // 首次加载只建基线，不响铃
    expect(vm.soundPlaying).toBe(false);

    // 折叠面板后模拟新告警到达
    vm.alarmPanelCollapsed = true;
    const { getProjectDetail } = await import("@/api/dashboard");
    const next = hoist.makeDetail();
    next.alarms = [
      {
        ...next.alarms[0],
        id: 2,
        alarm_info: "A防区触发告警",
        alarm_time: "2026-06-28T09:00:00",
      },
      next.alarms[0],
    ];
    (getProjectDetail as ReturnType<typeof vi.fn>).mockResolvedValueOnce(next);

    await vm.load();
    await flushPromises();

    expect(vm.soundPlaying).toBe(true);
    expect(vm.alarmPanelCollapsed).toBe(false);
    // 静音按钮可用
    expect(btnByText(wrapper, "静音")).toBeTruthy();

    vm.stopAlarmSound();
    await flushPromises();
    expect(vm.soundPlaying).toBe(false);
  });
});
