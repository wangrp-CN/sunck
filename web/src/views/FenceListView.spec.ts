// FenceListView 单测（电子围栏列表：查询/重置/权限/标点表格/绘制回填/删除/批量删除）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FenceListView from "@/views/FenceListView.vue";
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
    const permission_codes = ["fence:list", "fence:add", "fence:edit", "fence:delete"];
    return {
      user: { permission_codes },
      hasPermission: (code: string) => permission_codes.includes(code),
      loadProfile: vi.fn(),
    };
  }),
}));

// 页面用 useRoute 读取 ?project_id= 预选项目
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
}));

const fences = {
  items: [
    {
      id: 1,
      project_id: 1,
      project_name: "项目A",
      name: "围栏A",
      description: "外围防区",
      fence_type: "普通防区",
      enabled: true,
      geometry_wkt: "POLYGON((116.100000 39.100000, 116.200000 39.200000, 116.300000 39.100000, 116.100000 39.100000))",
      created_by: 1,
      created_at: "2026-08-06 10:00:00",
    },
  ],
  total: 1,
  page: 1,
  size: 10,
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

import { batchDeleteFences, deleteFence, fetchFences } from "@/api/fence";
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

describe("views/FenceListView.vue", () => {
  it("挂载后加载围栏列表与项目并渲染表格", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    expect(vi.mocked(fetchFences)).toHaveBeenCalled();
    expect((wrapper.vm as any).tableData.length).toBe(1);
    expect(wrapper.text()).toContain("围栏A");
    expect(wrapper.text()).toContain("项目A");
    expect(wrapper.text()).toContain("普通防区");
  });

  it("渲染原型定义的列头与操作入口", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const text = wrapper.text();
    ["序号", "项目名称", "围栏名称", "围栏类型", "围栏启用", "创建时间", "操作"].forEach((h) => {
      expect(text).toContain(h);
    });
    expect(text).toContain("查询");
    expect(text).toContain("重置");
    expect(text).toContain("新增");
    expect(text).toContain("查看");
    expect(text).toContain("编辑");
    expect(text).toContain("删除");
  });

  it("查询：按项目/名称/类型/启用状态组装参数并回到第 1 页", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "围栏";
    vm.query.fence_type = "预警防区";
    vm.query.enabled = false;
    await vm.handleSearch();
    expect(vi.mocked(fetchFences)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        project_id: 1,
        name: "围栏",
        fence_type: "预警防区",
        enabled: false,
        page: 1,
      }),
    );
  });

  it("重置：清空全部查询条件并重新加载", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "围栏";
    vm.query.fence_type = "报警防区";
    vm.query.enabled = true;
    await vm.handleReset();
    expect(vm.query.project_id).toBeNull();
    expect(vm.query.name).toBe("");
    expect(vm.query.fence_type).toBeNull();
    expect(vm.query.enabled).toBeNull();
    expect(vi.mocked(fetchFences)).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, project_id: undefined, name: undefined }),
    );
  });

  it("新增弹窗：默认普通防区 / 启用是，并继承列表已选项目", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.openCreate();
    expect(vm.form.project_id).toBe(1);
    expect(vm.form.fence_type).toBe("普通防区");
    expect(vm.form.enabled).toBe(true);
    expect(vm.points.length).toBe(0);
  });

  it("编辑弹窗：WKT 回填标点表格（去掉闭合重复点）", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.tableData[0]);
    expect(vm.form.name).toBe("围栏A");
    expect(vm.form.description).toBe("外围防区");
    // WKT 含 4 个点（首末重复），回填后应为 3 个标点
    expect(vm.points.length).toBe(3);
    expect(vm.geometryWkt).toContain("POLYGON");
  });

  it("标点表格：向上增加 / 向下增加 / 删除", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.tableData[0]);
    const before = vm.points.length;

    vm.addPointAbove(0);
    expect(vm.points.length).toBe(before + 1);
    expect(vm.points[0].lng).toBeNull();

    vm.addPointBelow(0);
    expect(vm.points.length).toBe(before + 2);

    vm.removePoint(0);
    vm.removePoint(0);
    expect(vm.points.length).toBe(before);

    vm.clearPoints();
    expect(vm.points.length).toBe(0);
    expect(vm.geometryWkt).toBeNull();
  });

  it("地图绘制回调：GCJ-02 顶点写入标点表格并生成 WGS-84 WKT", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    vm.onFenceDrawn({
      points: [
        [116.1, 39.1],
        [116.2, 39.2],
        [116.3, 39.3],
      ],
    });
    expect(vm.points.length).toBe(3);
    expect(vm.geometryWkt).toContain("POLYGON");
    expect(vm.previewFences.length).toBe(1);
  });

  it("顶点不足 3 点时不写入标点", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    vm.onFenceDrawn({
      points: [
        [116.1, 39.1],
        [116.2, 39.2],
      ],
    });
    expect(vm.points.length).toBe(0);
    expect(vm.geometryWkt).toBeNull();
  });

  it("删除：二次确认文案为「您确认删除当前电子围栏？」", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalledWith(
      "您确认删除当前电子围栏？",
      "删除确认",
      expect.any(Object),
    );
    expect(vi.mocked(deleteFence)).toHaveBeenCalledWith(1);
  });

  it("删除：用户取消时不调用接口", async () => {
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(deleteFence)).not.toHaveBeenCalled();
  });

  it("批量删除：工具条展示已选条数，未选中时按钮禁用", async () => {
    wrapper = mount(FenceListView);
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
    wrapper = mount(FenceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(fences.items);
    vi.mocked(fetchFences).mockClear();

    await vm.onBatchDelete();
    await flushPromises();

    expect(vi.mocked(batchDeleteFences)).toHaveBeenCalledWith([1]);
    expect(vi.mocked(fetchFences)).toHaveBeenCalled();
    expect(vm.selectedRows.length).toBe(0);
  });

  it("围栏类型与围栏启用为必填项（提交前必须选择）", () => {
    wrapper = mount(FenceListView);
    const vm = wrapper.vm as any;
    expect(vm.rules.fence_type[0].required).toBe(true);
    expect(vm.rules.enabled[0].required).toBe(true);
    expect(vm.rules.fence_type[0].message).toBe("请选择围栏类型");
    expect(vm.rules.enabled[0].message).toBe("请选择围栏启用状态");
  });

  // 围栏描述：可输入+下拉（allow-create）。下拉限高由 .fence-desc-popper 全局样式控制，
  // 弹层 DOM 在 jsdom 下不渲染，故此处校验数据契约：预设项存在、清空(=undefined)为 null、自由输入原样提交。
  it("围栏描述：可输入+下拉开型，清空为 null、自由输入原样提交", () => {
    wrapper = mount(FenceListView);
    const vm = wrapper.vm as any;
    expect(Array.isArray(vm.descriptionOptions)).toBe(true);
    expect(vm.descriptionOptions.length).toBeGreaterThan(0);

    vm.form.description = undefined;
    expect(vm.buildFenceData().description).toBeNull();

    vm.form.description = "自定义描述文本";
    expect(vm.buildFenceData().description).toBe("自定义描述文本");
  });

  // 注：新增标点按钮使用 type="primary" + .point-add-btn（加粗/主色阴影）实现高对比视觉，
  // 其渲染位于 el-dialog 内部；jsdom 下 el-dialog 的 rendered 门控不触发，无法在 DOM 断言，
  // 此处仅以规则校验覆盖「必填」语义，按钮视觉由代码审查保证一致。
});
