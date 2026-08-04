// FenceView 单测（围栏管理：列表/搜索/权限/绘制回填/删除）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FenceView from "@/views/FenceView.vue";
import { ElMessageBox } from "element-plus";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: vi.fn() },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => {
    const permission_codes = ["fence:add", "fence:edit", "fence:delete"];
    return {
      user: { permission_codes },
      hasPermission: (code: string) => permission_codes.includes(code),
      loadProfile: vi.fn(),
    };
  }),
}));

const fences = {
  items: [
    {
      id: 1,
      name: "围栏A",
      fence_type: "人员",
      enabled: true,
      project_id: 1,
      geometry_wkt: "POLYGON((116 39))",
    },
  ],
  total: 1,
};

vi.mock("@/api/fence", () => ({
  batchDeleteFences: vi.fn().mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  fetchFences: vi.fn(),
  fetchFence: vi.fn(),
  createFence: vi.fn(),
  updateFence: vi.fn(),
  deleteFence: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("@/components/MapPanel.vue", () => ({
  default: { name: "MapPanelStub", template: "<div class='map-stub'/>" },
}));

import { batchDeleteFences, fetchFences, deleteFence } from "@/api/fence";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchFences).mockResolvedValue(fences as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: 1, name: "项目A" }],
    total: 1,
  } as any);
  vi.mocked(deleteFence).mockResolvedValue(null);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/FenceView.vue", () => {
  it("挂载后加载围栏列表与项目并渲染表格", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    expect(vi.mocked(fetchFences)).toHaveBeenCalled();
    expect((wrapper.vm as any).tableData.length).toBe(1);
    expect(wrapper.text()).toContain("围栏A");
  });

  it("有权限时显示新增/编辑/删除操作", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    expect(wrapper.text()).toContain("新增围栏");
    expect(wrapper.text()).toContain("编辑");
    expect(wrapper.text()).toContain("删除");
  });

  it("搜索调用 fetchFences（带 keyword 并重置到第 1 页）", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.keyword = "围栏A";
    await vm.handleSearch();
    expect(vi.mocked(fetchFences)).toHaveBeenLastCalledWith(
      expect.objectContaining({ keyword: "围栏A", page: 1 }),
    );
  });

  it("绘制围栏回调：gcj02→wgs84 回填 geometry_wkt（POLYGON）", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onFenceDrawn({ points: [[116.1, 39.1], [116.2, 39.2], [116.3, 39.3]] });
    expect(vm.form.geometry_wkt).toContain("POLYGON");
    expect(vm.previewFences.length).toBe(1);
  });

  it("顶点不足时不回填（<3 点）", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.form.geometry_wkt = "";
    vm.onFenceDrawn({ points: [[116.1, 39.1], [116.2, 39.2]] });
    expect(vm.form.geometry_wkt).toBe("");
  });

  it("删除：确认后调用 deleteFence 并重载列表", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalled();
    expect(vi.mocked(deleteFence)).toHaveBeenCalledWith(1);
  });

  it("批量删除：工具条展示已选条数，未选中时按钮禁用", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const bar = wrapper.find(".batch-actions");
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain("已选择");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeDefined();

    (wrapper.vm as any).onSelectionChange(fences.items);
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".batch-actions").text()).toContain("1");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeUndefined();
  });

  it("批量删除：确认后调用 batchDeleteFences 并重新加载列表", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(fences.items);
    vi.mocked(fetchFences).mockClear();

    await vm.onBatchDelete();
    await flushPromises();

    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalled();
    expect(vi.mocked(batchDeleteFences)).toHaveBeenCalledWith([1]);
    expect(vi.mocked(fetchFences)).toHaveBeenCalled();
    expect(vm.selectedRows.length).toBe(0);
  });

  it("批量删除：用户取消确认时不调用接口", async () => {
    wrapper = mount(FenceView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(fences.items);
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));

    await vm.onBatchDelete();
    expect(vi.mocked(batchDeleteFences)).not.toHaveBeenCalled();
  });
});
