// LargeMachineListView 单测（大型机械列表：查询/重置/权限/弹窗/删除/批量删除）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LargeMachineListView from "@/views/LargeMachineListView.vue";
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
    const permission_codes = [
      "machine:list",
      "machine:add",
      "machine:edit",
      "machine:delete",
    ];
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

const machines = {
  items: [
    {
      id: 1,
      project_id: 1,
      project_name: "项目A",
      machine_no: "M001",
      machine_type: "挖掘机",
      spec_model: "XL-200",
      description: "主臂挖掘机",
      created_by: 1,
      created_at: "2024-06-28 08:27:10",
    },
    {
      id: 2,
      project_id: 1,
      project_name: "项目A",
      machine_no: "M002",
      machine_type: "打桩机",
      spec_model: null,
      description: null,
      created_by: 1,
      created_at: "2024-06-29 09:00:00",
    },
  ],
  total: 2,
  page: 1,
  size: 20,
};

vi.mock("@/api/machine", () => ({
  batchDeleteMachines: vi.fn().mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  fetchMachines: vi.fn(),
  fetchMachine: vi.fn(),
  createMachine: vi.fn(),
  updateMachine: vi.fn(),
  deleteMachine: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));

import {
  batchDeleteMachines,
  deleteMachine,
  fetchMachines,
} from "@/api/machine";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchMachines).mockResolvedValue(machines as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: 1, name: "项目A" }],
    total: 1,
  } as any);
  vi.mocked(deleteMachine).mockResolvedValue(null);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/LargeMachineListView.vue", () => {
  it("挂载后加载大机列表与项目并渲染表格", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    expect(vi.mocked(fetchMachines)).toHaveBeenCalled();
    expect((wrapper.vm as any).tableData.length).toBe(2);
    expect(wrapper.text()).toContain("M001");
    expect(wrapper.text()).toContain("项目A");
    expect(wrapper.text()).toContain("挖掘机");
  });

  it("渲染原型定义的列头与操作入口", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const text = wrapper.text();
    [
      "序号",
      "项目名称",
      "大机编号",
      "大机类型",
      "规格及型号",
      "大机设备说明",
      "创建时间",
      "操作",
    ].forEach((h) => {
      expect(text).toContain(h);
    });
    expect(text).toContain("查询");
    expect(text).toContain("重置");
    expect(text).toContain("新增");
    expect(text).toContain("查看");
    expect(text).toContain("编辑");
    expect(text).toContain("删除");
  });

  it("查询：按项目/编号/类型组装参数并回到第 1 页", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.machine_no = "M001";
    vm.query.machine_type = "挖掘机";
    await vm.handleSearch();
    expect(vi.mocked(fetchMachines)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        project_id: 1,
        machine_no: "M001",
        machine_type: "挖掘机",
        page: 1,
      }),
    );
  });

  it("重置：清空全部查询条件并重新加载", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.machine_no = "M001";
    vm.query.machine_type = "挖掘机";
    await vm.handleReset();
    expect(vm.query.project_id).toBeNull();
    expect(vm.query.machine_no).toBe("");
    expect(vm.query.machine_type).toBeNull();
    expect(vi.mocked(fetchMachines)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 1,
        project_id: undefined,
        machine_no: undefined,
        machine_type: undefined,
      }),
    );
  });

  it("新增弹窗：继承列表已选项目，默认无类型", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.openCreate();
    expect(vm.form.project_id).toBe(1);
    expect(vm.form.machine_type).toBe("");
  });

  it("编辑弹窗：回填字段（含大机类型与说明）", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.tableData[0]);
    expect(vm.form.machine_no).toBe("M001");
    expect(vm.form.machine_type).toBe("挖掘机");
    expect(vm.form.spec_model).toBe("XL-200");
  });

  it("删除：二次确认文案为「您确认删除当前大机？」", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalledWith(
      "您确认删除当前大机？",
      "删除确认",
      expect.any(Object),
    );
    expect(vi.mocked(deleteMachine)).toHaveBeenCalledWith(1);
  });

  it("删除：用户取消时不调用接口", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(deleteMachine)).not.toHaveBeenCalled();
  });

  it("批量删除：工具条展示已选条数，未选中时按钮禁用", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const bar = wrapper.find(".batch-actions");
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain("已选择");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeDefined();

    (wrapper.vm as any).onSelectionChange(machines.items);
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".batch-actions").text()).toContain("2");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeUndefined();
  });

  it("批量删除：确认后调用 batchDeleteMachines 并重新加载列表", async () => {
    wrapper = mount(LargeMachineListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(machines.items);
    vi.mocked(fetchMachines).mockClear();

    await vm.onBatchDelete();
    await flushPromises();

    expect(vi.mocked(batchDeleteMachines)).toHaveBeenCalledWith([1, 2]);
    expect(vi.mocked(fetchMachines)).toHaveBeenCalled();
    expect(vm.selectedRows.length).toBe(0);
  });
});
