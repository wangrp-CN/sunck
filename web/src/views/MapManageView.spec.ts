// MapManageView 单测（系统管理·地图维护：列表加载、权限按钮、新增对话框）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapManageView from "@/views/MapManageView.vue";

const hoist = vi.hoisted(() => {
  const sample = {
    id: 1,
    name: "XX站平面图",
    type: "station_plan",
    project_id: 1,
    center_lng: 116.397,
    center_lat: 39.908,
    zoom: 12,
    coverage_wkt: null,
    image_url: null,
    remark: "测试",
    operator: "tester",
    created_at: null,
    updated_at: null,
  };
  return { sample };
});

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: {
      permission_codes: ["map:list", "map:add", "map:edit", "map:delete"],
    },
    loadProfile: vi.fn(),
  })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/maps", meta: {}, query: {} }),
}));

vi.mock("@/api/maps", () => ({
  fetchMapAssets: vi.fn().mockResolvedValue({
    items: [hoist.sample],
    total: 1,
    page: 1,
    size: 20,
  }),
  createMapAsset: vi.fn().mockResolvedValue(hoist.sample),
  updateMapAsset: vi.fn().mockResolvedValue(hoist.sample),
  deleteMapAsset: vi.fn().mockResolvedValue(undefined),
  fetchMapAsset: vi.fn().mockResolvedValue(hoist.sample),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, size: 1000 }),
}));

vi.mock("@/api/media", () => ({
  uploadMedia: vi.fn().mockResolvedValue([{ url: "/api/v1/media/key/x.png" }]),
}));

describe("MapManageView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("挂载并加载列表，渲染资源行", async () => {
    const wrapper = mount(MapManageView);
    await flushPromises();
    expect(wrapper.text()).toContain("XX站平面图");
  });

  it("拥有 map:add 权限时显示「新增资源」按钮", async () => {
    const wrapper = mount(MapManageView);
    await flushPromises();
    expect(wrapper.text()).toContain("新增资源");
  });

  it("点击新增资源弹出对话框", async () => {
    const wrapper = mount(MapManageView);
    await flushPromises();
    const btn = wrapper.findAll("button").find((b) => b.text().includes("新增资源"));
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("新增地图资源");
  });
});
