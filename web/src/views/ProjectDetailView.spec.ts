// ProjectDetailView 单测（大屏·项目详情页：信息栏/搜索/大机弹窗/告警处置）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectDetailView from "@/views/ProjectDetailView.vue";

const hoist = vi.hoisted(() => {
  const detail = {
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
        report_time: null,
      },
    ],
    fences: [
      { id: 1, name: "F1", fence_type: "电子围栏", geometry_wkt: "POLYGON((0 0,0 1,1 1,1 0,0 0))", enabled: true },
    ],
    persons: [
      { id: 1, person_no: "PN1", name: "张三", person_type: "防护", device_no: "D1" },
    ],
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
        alarm_type: "围栏告警",
        device_type: null,
        device_name: null,
        device_no: null,
        alarm_level: "严重",
        alarm_info: "机械进入围栏触发报警",
        alarm_status: "active",
        handle_status: "待处理",
        fence_name: "F1",
        alarm_time: "2026-06-28T08:27:10",
      },
    ],
  };
  return { detail };
});

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn(), resolve: () => ({ href: "/track" }) }),
  useRoute: () => ({ params: { id: "1" }, query: {}, path: "/projects/1/detail", meta: {} }),
}));

vi.mock("@/api/dashboard", () => ({
  getProjectDetail: vi.fn().mockResolvedValue(hoist.detail),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: vi
    .fn()
    .mockResolvedValue({ items: [{ id: 1, name: "P项目" }], total: 1, page: 1, size: 200 }),
}));

vi.mock("@/api/alarm", () => ({
  handleAlarm: vi.fn().mockResolvedValue({}),
}));

vi.mock("@/components/MapPanel.vue", () => ({
  default: {
    name: "MapPanel",
    template: "<div class='map-mock'></div>",
    methods: { focusDevice() {} },
  },
}));

function btnByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text));
}

describe("ProjectDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom 未实现 window.open，桩掉避免告警
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  it("渲染项目信息栏、搜索区与告警面板（含 处理/忽略）", async () => {
    const wrapper = mount(ProjectDetailView, {
      global: { directives: { loading: { mounted() {}, updated() {} } } },
    });
    await flushPromises();
    const text = wrapper.text();
    // 项目信息栏
    expect(text).toContain("项目简称：");
    expect(text).toContain("开工日期：");
    expect(text).toContain("完工日期：");
    expect(text).toContain("区间：");
    expect(text).toContain("里程：");
    // 搜索区
    expect(text).toContain("搜索方式：");
    // 告警面板
    expect(text).toContain("告警信息");
    expect(text).toContain("告警类型");
    expect(text).toContain("处理");
    expect(text).toContain("忽略");
  });

  it("搜索大机弹出详情：含防护人员姓名/坐标/大机类型，查看轨迹可点击", async () => {
    const wrapper = mount(ProjectDetailView, {
      global: { directives: { loading: { mounted() {}, updated() {} } } },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      searchType: string;
      searchEntityId: number | null;
    };
    vm.searchType = "machine";
    vm.searchEntityId = 1;
    await flushPromises();

    await btnByText(wrapper, "搜索")!.trigger("click");
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("大机名称：");
    expect(text).toContain("大机编号：");
    // 图2 字段：防护人员姓名 / 坐标 / 大机类型
    expect(text).toContain("防护人员姓名：张三");
    expect(text).toContain("坐标：116.400000，39.900000");
    expect(text).toContain("大机类型：捣固车");
    // 查看轨迹按钮存在且非禁用（track_device_no 已解析）
    const trackBtn = btnByText(wrapper, "查看轨迹")!;
    expect(trackBtn.attributes("disabled")).toBeUndefined();
  });

  it("搜索人员弹出详情：含人员姓名/编号/设备/坐标 + 查看轨迹", async () => {
    const wrapper = mount(ProjectDetailView, {
      global: { directives: { loading: { mounted() {}, updated() {} } } },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      searchType: string;
      searchEntityId: number | null;
    };
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

  it("点击告警「处理」调用 handleAlarm 并置为已处理", async () => {
    const wrapper = mount(ProjectDetailView, {
      global: { directives: { loading: { mounted() {}, updated() {} } } },
    });
    await flushPromises();

    const handleMock = (await import("@/api/alarm")).handleAlarm as ReturnType<typeof vi.fn>;
    handleMock.mockClear();

    await btnByText(wrapper, "处理")!.trigger("click");
    await flushPromises();

    expect(handleMock).toHaveBeenCalledTimes(1);
    expect(handleMock.mock.calls[0][0]).toBe(1); // alarm id
    expect(handleMock.mock.calls[0][1]).toEqual({ handle_status: "已处理" });
    // 列表内该告警操作列不再显示「处理」（已处理）
    expect(wrapper.text()).toContain("已处理");
  });
});
