// HazardView 单测（隐患治理：加载列表/统计、筛选、状态流转、权限）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HazardView from "@/views/HazardView.vue";

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
    user: { permission_codes: ["hazard:list", "hazard:handle", "hazard:create", "hazard:update", "hazard:delete"] },
    loadProfile: vi.fn(),
  })),
}));

const hazards = {
  items: [
    {
      id: 1,
      project_id: 1,
      project_name: "示范项目",
      title: "桥墩旁堆放杂物",
      level: "较大",
      category: "施工安全",
      description: "易燃物",
      location_desc: "K123+200",
      lng: 116.3,
      lat: 39.9,
      discovered_by_name: "张三",
      discovered_at: "2026-07-20T09:00:00",
      source: "人工",
      status: "待整改",
      assignee_id: 10,
      assignee_name: "李四",
      due_at: "2026-07-25T18:00:00",
      rectify_note: null,
      rectify_at: null,
      verify_by_name: null,
      verify_at: null,
      verify_note: null,
      closed_at: null,
      created_by: 1,
      created_at: "2026-07-20T09:00:00",
      updated_at: null,
      is_overdue: false,
    },
    {
      id: 2,
      project_id: 1,
      project_name: "示范项目",
      title: "设备未接地",
      level: "一般",
      category: "设备设施",
      description: null,
      location_desc: null,
      lng: null,
      lat: null,
      discovered_by_name: null,
      discovered_at: null,
      source: "巡检",
      status: "整改中",
      assignee_id: null,
      assignee_name: null,
      due_at: null,
      rectify_note: null,
      rectify_at: null,
      verify_by_name: null,
      verify_at: null,
      verify_note: null,
      closed_at: null,
      created_by: 1,
      created_at: "2026-07-19T09:00:00",
      updated_at: null,
      is_overdue: false,
    },
  ],
  total: 2,
};

vi.mock("@/api/hazard", () => ({
  fetchHazards: vi.fn(),
  fetchHazardStats: vi.fn(),
  fetchHazardOptions: vi.fn(),
  createHazard: vi.fn(),
  updateHazard: vi.fn(),
  deleteHazard: vi.fn(),
  transitionHazard: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("@/api/person", () => ({ fetchPersons: vi.fn() }));
vi.mock("@/components/MapPanel.vue", () => ({
  default: { name: "M", template: "<div/>", methods: { setMovingMarker() {} } },
}));

import {
  createHazard,
  deleteHazard,
  fetchHazardOptions,
  fetchHazardStats,
  fetchHazards,
  transitionHazard,
} from "@/api/hazard";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchHazards).mockResolvedValue(hazards as any);
  vi.mocked(fetchHazardStats).mockResolvedValue({
    total: 2,
    by_status: { 待整改: 1, 整改中: 1 },
    by_level: { 较大: 1, 一般: 1 },
    overdue: 0,
  } as any);
  vi.mocked(fetchHazardOptions).mockResolvedValue({
    levels: ["重大", "较大", "一般", "低"],
    categories: ["施工安全", "设备设施", "环境", "管理", "其他"],
    sources: ["人工", "巡检", "系统"],
    statuses: ["待整改", "整改中", "待复核", "已销号", "已驳回"],
  } as any);
});

describe("views/HazardView.vue", () => {
  it("挂载后加载列表与统计", async () => {
    wrapper = mount(HazardView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vi.mocked(fetchHazards)).toHaveBeenCalled();
    expect(vi.mocked(fetchHazardStats)).toHaveBeenCalled();
    expect(vm.list.length).toBe(2);
    expect(vm.total).toBe(2);
    expect(vm.stats.total).toBe(2);
  });

  it("应用筛选：回到第1页并带条件重载", async () => {
    wrapper = mount(HazardView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.page = 3;
    vm.filters.status = "待整改";
    await vm.applyFilters();
    await flushPromises();
    expect(vm.page).toBe(1);
    expect(vi.mocked(fetchHazards)).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "待整改", page: 1 }),
    );
  });

  it("新增隐患调用 createHazard 并刷新", async () => {
    vi.mocked(createHazard).mockResolvedValue({ id: 3 } as any);
    wrapper = mount(HazardView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    vm.form.title = "新隐患";
    await vm.submitForm();
    await flushPromises();
    expect(vi.mocked(createHazard)).toHaveBeenCalledWith(
      expect.objectContaining({ title: "新隐患" }),
    );
  });

  it("状态流转：待整改→开始整改 调用 transitionHazard", async () => {
    vi.mocked(transitionHazard).mockResolvedValue({ id: 1, status: "整改中" } as any);
    wrapper = mount(HazardView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openTransition(vm.list[0]);
    vm.transAction = "start_rectify";
    await vm.submitTransition();
    await flushPromises();
    expect(vi.mocked(transitionHazard)).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ action: "start_rectify" }),
    );
  });

  it("删除隐患调用 deleteHazard 并刷新", async () => {
    vi.mocked(deleteHazard).mockResolvedValue({ id: 1 } as any);
    wrapper = mount(HazardView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.list[0]);
    await flushPromises();
    expect(vi.mocked(deleteHazard)).toHaveBeenCalledWith(1);
  });

  it("权限：hazard:* 命中时 canCreate/canHandle 为 true", async () => {
    wrapper = mount(HazardView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vm.canCreate).toBe(true);
    expect(vm.canHandle).toBe(true);
  });
});
