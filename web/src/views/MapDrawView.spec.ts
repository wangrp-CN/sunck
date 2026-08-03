// MapDrawView 单测（地图维护·手动绘制：模式切换、必填校验、坐标画点保存、取消）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapDrawView from "@/views/MapDrawView.vue";

const hoist = vi.hoisted(() => {
  const sample = {
    id: 7,
    name: "施工便道入口",
    kind: "point",
    mode: "free",
    project_id: null,
    geometry: "[[116.397,39.908]]",
    points: [[116.397, 39.908]],
    center_lng: 116.397,
    center_lat: 39.908,
    length_m: null,
    color: "#f56c6c",
    remark: "测试",
    operator: "tester",
    created_at: "2026-08-03T10:00:00",
    updated_at: null,
  };
  return { sample };
});

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: {
      confirm: vi.fn().mockResolvedValue(true),
      prompt: vi.fn().mockResolvedValue({ value: "新名称" }),
    },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => {
    const permission_codes = ["map:list", "map:add", "map:edit", "map:delete"];
    return {
      user: { permission_codes },
      hasPermission: (code: string) => permission_codes.includes(code),
      loadProfile: vi.fn(),
    };
  }),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/maps/draw", meta: {}, query: {} }),
}));

vi.mock("@/api/map_drawings", () => ({
  fetchMapDrawings: vi.fn().mockResolvedValue({
    items: [hoist.sample],
    total: 1,
    page: 1,
    size: 10,
  }),
  createMapDrawing: vi.fn().mockResolvedValue(hoist.sample),
  updateMapDrawing: vi.fn().mockResolvedValue(hoist.sample),
  deleteMapDrawing: vi.fn().mockResolvedValue(undefined),
  fetchMapDrawing: vi.fn().mockResolvedValue(hoist.sample),
  fetchMapDrawingOptions: vi.fn().mockResolvedValue({
    kinds: [
      { value: "point", label: "标注点" },
      { value: "line", label: "标注线" },
    ],
    modes: [
      { value: "free", label: "自由绘制" },
      { value: "coord", label: "坐标录入" },
      { value: "road", label: "沿路绘制" },
    ],
    kind_modes: { point: ["free", "coord"], line: ["free", "road"] },
  }),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, size: 1000 }),
}));

function btnByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text));
}

describe("MapDrawView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("渲染四种绘制模式与已保存标注列表", async () => {
    const wrapper = mount(MapDrawView);
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("自由画点");
    expect(text).toContain("坐标画点");
    expect(text).toContain("自由画线");
    expect(text).toContain("沿路画线");
    expect(text).toContain("施工便道入口");
  });

  it("选择模式后进入绘制状态并显示对应名称标签", async () => {
    const wrapper = mount(MapDrawView);
    await flushPromises();
    expect(wrapper.text()).toContain("未开始绘制");

    await btnByText(wrapper, "自由画线")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("绘制中：自由画线");
    expect(wrapper.text()).toContain("线名称");
  });

  it("名称为空时保存被拦截，不调用创建接口", async () => {
    const { createMapDrawing } = await import("@/api/map_drawings");
    const wrapper = mount(MapDrawView);
    await flushPromises();

    await btnByText(wrapper, "自由画点")!.trigger("click");
    await btnByText(wrapper, "保存")!.trigger("click");
    await flushPromises();

    expect(createMapDrawing).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("点名称为必填项");
  });

  it("坐标画点：定位后填写名称可保存并持久化", async () => {
    const { createMapDrawing } = await import("@/api/map_drawings");
    const wrapper = mount(MapDrawView);
    await flushPromises();

    await btnByText(wrapper, "坐标画点")!.trigger("click");
    await flushPromises();

    await wrapper.find('input[placeholder="如 116.397428"]').setValue("116.5");
    await wrapper.find('input[placeholder="如 39.90923"]').setValue("39.95");
    await btnByText(wrapper, "在地图上定位")!.trigger("click");
    await flushPromises();

    await wrapper.find('input[placeholder="必填，如：新增便道口"]').setValue("新增路口");
    await btnByText(wrapper, "保存")!.trigger("click");
    await flushPromises();

    expect(createMapDrawing).toHaveBeenCalledTimes(1);
    const payload = (createMapDrawing as unknown as { mock: { calls: unknown[][] } }).mock
      .calls[0][0] as Record<string, unknown>;
    expect(payload.name).toBe("新增路口");
    expect(payload.kind).toBe("point");
    expect(payload.mode).toBe("coord");
    expect(payload.points).toEqual([[116.5, 39.95]]);
  });

  it("取消后退出绘制模式并清空草稿", async () => {
    const wrapper = mount(MapDrawView);
    await flushPromises();

    await btnByText(wrapper, "沿路画线")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("绘制中：沿路画线");

    await btnByText(wrapper, "取消")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("未开始绘制");
    expect(wrapper.text()).toContain("已采集节点：0");
  });
});
