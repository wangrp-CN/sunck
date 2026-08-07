// LocateDeviceListView 单测（人机定位设备列表：查询/重置/权限/弹窗/删除/批量删除）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LocateDeviceListView from "@/views/LocateDeviceListView.vue";
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
      "locate_device:list",
      "locate_device:add",
      "locate_device:edit",
      "locate_device:delete",
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

const locateDevices = {
  items: [
    {
      id: 1,
      project_id: 1,
      project_name: "项目A",
      name: "大机机械定位设备01",
      device_no: "011",
      device_type: "大机机械定位设备",
      function: "大机实时定位",
      sn: "SN001",
      status: "在线",
      created_by: 1,
      created_at: "2024-06-28 08:27:10",
    },
    {
      id: 2,
      project_id: 1,
      project_name: "项目A",
      name: "手持机定位设备01",
      device_no: "021",
      device_type: "人员手持机定位设备",
      function: null,
      sn: null,
      status: "不在线",
      created_by: 1,
      created_at: "2024-06-29 09:00:00",
    },
  ],
  total: 2,
  page: 1,
  size: 10,
};

vi.mock("@/api/locateDevice", () => ({
  batchDeleteLocateDevices: vi.fn().mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  fetchLocateDevices: vi.fn(),
  fetchLocateDevice: vi.fn(),
  createLocateDevice: vi.fn(),
  updateLocateDevice: vi.fn(),
  deleteLocateDevice: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));

import {
  batchDeleteLocateDevices,
  deleteLocateDevice,
  fetchLocateDevices,
} from "@/api/locateDevice";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchLocateDevices).mockResolvedValue(locateDevices as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: 1, name: "项目A" }],
    total: 1,
  } as any);
  vi.mocked(deleteLocateDevice).mockResolvedValue(null);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/LocateDeviceListView.vue", () => {
  it("挂载后加载设备列表与项目并渲染表格", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    expect(vi.mocked(fetchLocateDevices)).toHaveBeenCalled();
    expect((wrapper.vm as any).tableData.length).toBe(2);
    expect(wrapper.text()).toContain("大机机械定位设备01");
    expect(wrapper.text()).toContain("项目A");
    expect(wrapper.text()).toContain("大机机械定位设备");
  });

  it("渲染原型定义的列头与操作入口", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const text = wrapper.text();
    [
      "序号",
      "项目名称",
      "设备名称",
      "设备类型",
      "设备编号",
      "设备状态",
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

  it("查询：按项目/名称/类型/编号/状态组装参数并回到第 1 页", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "大机";
    vm.query.device_type = "大机机械定位设备";
    vm.query.device_no = "011";
    vm.query.status = "在线";
    await vm.handleSearch();
    expect(vi.mocked(fetchLocateDevices)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        project_id: 1,
        name: "大机",
        device_type: "大机机械定位设备",
        device_no: "011",
        status: "在线",
        page: 1,
      }),
    );
  });

  it("重置：清空全部查询条件并重新加载", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "大机";
    vm.query.device_type = "大机机械定位设备";
    vm.query.device_no = "011";
    vm.query.status = "在线";
    await vm.handleReset();
    expect(vm.query.project_id).toBeNull();
    expect(vm.query.name).toBe("");
    expect(vm.query.device_type).toBeNull();
    expect(vm.query.device_no).toBe("");
    expect(vm.query.status).toBeNull();
    expect(vi.mocked(fetchLocateDevices)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 1,
        project_id: undefined,
        name: undefined,
        device_type: undefined,
        device_no: undefined,
        status: undefined,
      }),
    );
  });

  it("新增弹窗：默认设备类型/状态，并继承列表已选项目", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.openCreate();
    expect(vm.form.project_id).toBe(1);
    expect(vm.form.device_type).toBe("人员手持机定位设备");
    expect(vm.form.status).toBe("在线");
  });

  it("编辑弹窗：回填字段（含设备类型与状态）", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.tableData[0]);
    expect(vm.form.name).toBe("大机机械定位设备01");
    expect(vm.form.device_type).toBe("大机机械定位设备");
    expect(vm.form.status).toBe("在线");
  });

  it("删除：二次确认文案为「您确认删除当前设备？」", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalledWith(
      "您确认删除当前设备？",
      "删除确认",
      expect.any(Object),
    );
    expect(vi.mocked(deleteLocateDevice)).toHaveBeenCalledWith(1);
  });

  it("删除：用户取消时不调用接口", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(deleteLocateDevice)).not.toHaveBeenCalled();
  });

  it("批量删除：工具条展示已选条数，未选中时按钮禁用", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const bar = wrapper.find(".batch-actions");
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain("已选择");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeDefined();

    (wrapper.vm as any).onSelectionChange(locateDevices.items);
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".batch-actions").text()).toContain("2");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeUndefined();
  });

  it("批量删除：确认后调用 batchDeleteLocateDevices 并重新加载列表", async () => {
    wrapper = mount(LocateDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(locateDevices.items);
    vi.mocked(fetchLocateDevices).mockClear();

    await vm.onBatchDelete();
    await flushPromises();

    expect(vi.mocked(batchDeleteLocateDevices)).toHaveBeenCalledWith([1, 2]);
    expect(vi.mocked(fetchLocateDevices)).toHaveBeenCalled();
    expect(vm.selectedRows.length).toBe(0);
  });
});
