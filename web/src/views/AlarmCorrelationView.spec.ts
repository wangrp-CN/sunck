// 跨设备根因关联页面单测：渲染、热力图→列表下钻联动、清除筛选
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import AlarmCorrelationView from "@/views/AlarmCorrelationView.vue";

const hoisted = vi.hoisted(() => ({
  getCorrelations: vi.fn(),
  getCorrelationTrend: vi.fn(),
  getCorrelationHeatmap: vi.fn(),
  getCorrelationMembers: vi.fn(),
  runCorrelations: vi.fn(),
  createCorrelationSocket: vi.fn(() => () => {}),
  elMessageSuccess: vi.fn(),
  elMessageInfo: vi.fn(),
  authUser: { is_superuser: true, permission_codes: [] as string[] },
}));

vi.mock("@/api/metrics", () => ({
  getCorrelations: (...a: any[]) => hoisted.getCorrelations(...a),
  getCorrelationTrend: (...a: any[]) => hoisted.getCorrelationTrend(...a),
  getCorrelationHeatmap: (...a: any[]) => hoisted.getCorrelationHeatmap(...a),
  getCorrelationMembers: (...a: any[]) => hoisted.getCorrelationMembers(...a),
  runCorrelations: (...a: any[]) => hoisted.runCorrelations(...a),
}));

vi.mock("@/utils/correlationWs", () => ({
  createCorrelationSocket: (...a: any[]) => hoisted.createCorrelationSocket(...a),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({ user: hoisted.authUser, hasPermission: () => true })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/intelligence/correlation", meta: { title: "跨设备根因关联" } }),
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: {
      success: (...a: any[]) => hoisted.elMessageSuccess(...a),
      warning: vi.fn(),
      error: vi.fn(),
      info: (...a: any[]) => hoisted.elMessageInfo(...a),
    },
    ElNotification: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

const ITEMS = [
  {
    id: 1,
    project_id: 100,
    project_name: "示范项目",
    spatial_type: "geo" as const,
    scope_key: "geo:1,2",
    fence_name: null,
    grid_cell: "1,2",
    started_at: "2026-07-20T08:00:00",
    ended_at: "2026-07-20T08:30:00",
    alarm_count: 5,
    device_count: 3,
    is_cross_device: true,
    max_level: "警告",
    device_nos: ["D1", "D2", "D3"],
    levels: ["警告"],
    alarm_types: [],
    alarm_ids: [1, 2],
    root_cause_hint: "同一地理网格短时集中告警",
    computed_at: "2026-07-20T09:00:00",
  },
  {
    // 同网格、不同时窗的事件组 → 同地点下钻应一并命中
    id: 3,
    project_id: 100,
    project_name: "示范项目",
    spatial_type: "geo" as const,
    scope_key: "geo:1,2",
    fence_name: null,
    grid_cell: "1,2",
    started_at: "2026-07-21T08:00:00",
    ended_at: "2026-07-21T08:30:00",
    alarm_count: 2,
    device_count: 2,
    is_cross_device: true,
    max_level: "提示",
    device_nos: ["D1", "D2"],
    levels: ["提示"],
    alarm_types: [],
    alarm_ids: [3, 4],
    root_cause_hint: null,
    computed_at: "2026-07-21T09:00:00",
  },
  {
    id: 2,
    project_id: 200,
    project_name: "其他项目",
    spatial_type: "fence" as const,
    scope_key: "fence:F1",
    fence_name: "F1",
    grid_cell: null,
    started_at: "2026-07-20T10:00:00",
    ended_at: "2026-07-20T10:30:00",
    alarm_count: 4,
    device_count: 2,
    is_cross_device: true,
    max_level: "严重",
    device_nos: ["D9", "D10"],
    levels: ["严重"],
    alarm_types: [],
    alarm_ids: [5, 6],
    root_cause_hint: "围栏内多设备告警",
    computed_at: "2026-07-20T11:00:00",
  },
];

const HEAT_POINT = {
  id: 1,
  project_id: 100,
  project_name: "示范项目",
  spatial_type: "geo" as const,
  fence_name: null,
  grid_cell: "1,2",
  lng: 120.1,
  lat: 30.2,
  gcj02: { lng: 120.11, lat: 30.21 },
  weight: 5,
  alarm_count: 5,
  device_count: 3,
  max_level: "警告",
  is_cross_device: true,
  root_cause_hint: "同一地理网格短时集中告警",
};

function setup() {
  hoisted.getCorrelations.mockResolvedValue({ total: ITEMS.length, items: ITEMS });
  hoisted.getCorrelationTrend.mockResolvedValue({ series: [] });
  hoisted.getCorrelationHeatmap.mockResolvedValue({ total: 1, points: [HEAT_POINT] });
  hoisted.getCorrelationMembers.mockResolvedValue({ items: [] });
  hoisted.runCorrelations.mockResolvedValue({ groups: 3, cross_device_groups: 2 });
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("AlarmCorrelationView", () => {
  it("renders title and loads all event groups", async () => {
    setup();
    const wrapper = mount(AlarmCorrelationView);
    await flushPromises();

    expect(wrapper.text()).toContain("跨设备根因关联");
    expect(hoisted.getCorrelations).toHaveBeenCalled();
    // 默认未筛选：表格展示全部 3 个事件组
    expect((wrapper.vm as any).filteredItems.length).toBe(3);
  });

  it("clicking a heat point drills down: filters list to same-scope groups", async () => {
    setup();
    const wrapper = mount(AlarmCorrelationView);
    await flushPromises();

    await (wrapper.vm as any).onHeatSelect(HEAT_POINT);
    await flushPromises();

    // 精确 id=1 + 同网格 id=3 → 命中 2 组；project 200 的被排除
    expect((wrapper.vm as any).selectedPoint?.id).toBe(1);
    expect((wrapper.vm as any).filteredItems.length).toBe(2);
    expect((wrapper.vm as any).filteredItems.every((i: any) => i.grid_cell === "1,2")).toBe(true);
    expect(hoisted.elMessageSuccess).toHaveBeenCalled();
    expect((wrapper.vm as any).$el.querySelector(".heat-filter")).toBeTruthy();
  });

  it("clicking the same heat point again toggles the filter off", async () => {
    setup();
    const wrapper = mount(AlarmCorrelationView);
    await flushPromises();

    await (wrapper.vm as any).onHeatSelect(HEAT_POINT);
    await flushPromises();
    expect((wrapper.vm as any).selectedPoint).not.toBeNull();

    await (wrapper.vm as any).onHeatSelect(HEAT_POINT);
    await flushPromises();
    expect((wrapper.vm as any).selectedPoint).toBeNull();
    expect((wrapper.vm as any).filteredItems.length).toBe(3);
  });

  it("clearHeatFilter restores the full list", async () => {
    setup();
    const wrapper = mount(AlarmCorrelationView);
    await flushPromises();

    await (wrapper.vm as any).onHeatSelect(HEAT_POINT);
    await flushPromises();
    expect((wrapper.vm as any).filteredItems.length).toBe(2);

    await (wrapper.vm as any).clearHeatFilter();
    await flushPromises();
    expect((wrapper.vm as any).selectedPoint).toBeNull();
    expect((wrapper.vm as any).filteredItems.length).toBe(3);
  });
});
