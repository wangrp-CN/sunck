// AntiIntrusionDeviceListView 单测（大机防侵限设备列表：查询/重置/权限/弹窗/删除/批量删除）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AntiIntrusionDeviceListView from "@/views/AntiIntrusionDeviceListView.vue";
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
      "anti_intrusion_device:list",
      "anti_intrusion_device:add",
      "anti_intrusion_device:edit",
      "anti_intrusion_device:delete",
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

const antiDevices = {
  items: [
    {
      id: 1,
      project_id: 1,
      project_name: "项目A",
      name: "大机防侵限设备01",
      device_no: "011",
      sn: "SN001",
      longitude: 116.397,
      latitude: 39.909,
      status: "在线",
      created_by: 1,
      created_at: "2024-06-28 08:27:10",
    },
    {
      id: 2,
      project_id: 1,
      project_name: "项目A",
      name: "大机防侵限设备02",
      device_no: "012",
      sn: null,
      longitude: null,
      latitude: null,
      status: "不在线",
      created_by: 1,
      created_at: "2024-06-27 08:27:10",
    },
  ],
  total: 2,
  page: 1,
  size: 10,
};

vi.mock("@/api/antiIntrusionDevice", () => ({
  batchDeleteAntiIntrusionDevices: vi
    .fn()
    .mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  fetchAntiIntrusionDevices: vi.fn(),
  fetchAntiIntrusionDevice: vi.fn(),
  createAntiIntrusionDevice: vi.fn(),
  updateAntiIntrusionDevice: vi.fn(),
  deleteAntiIntrusionDevice: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));

import {
  batchDeleteAntiIntrusionDevices,
  deleteAntiIntrusionDevice,
  fetchAntiIntrusionDevices,
} from "@/api/antiIntrusionDevice";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchAntiIntrusionDevices).mockResolvedValue(antiDevices as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: 1, name: "项目A" }],
    total: 1,
  } as any);
  vi.mocked(deleteAntiIntrusionDevice).mockResolvedValue(null);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/AntiIntrusionDeviceListView.vue", () => {
  it("挂载后加载设备列表与项目并渲染表格", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    expect(vi.mocked(fetchAntiIntrusionDevices)).toHaveBeenCalled();
    expect((wrapper.vm as any).tableData.length).toBe(2);
    expect(wrapper.text()).toContain("大机防侵限设备01");
    expect(wrapper.text()).toContain("项目A");
  });

  it("渲染原型定义的列头与操作入口", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const text = wrapper.text();
    ["序号", "项目名称", "设备名称", "设备编号", "设备状态", "创建时间", "操作"].forEach(
      (h) => {
        expect(text).toContain(h);
      },
    );
    expect(text).toContain("查询");
    expect(text).toContain("重置");
    expect(text).toContain("新增");
    expect(text).toContain("查看");
    expect(text).toContain("编辑");
    expect(text).toContain("删除");
  });

  it("查询：按项目/名称/编号/状态组装参数并回到第 1 页", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "大机";
    vm.query.device_no = "011";
    vm.query.status = "在线";
    await vm.handleSearch();
    expect(vi.mocked(fetchAntiIntrusionDevices)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        project_id: 1,
        name: "大机",
        device_no: "011",
        status: "在线",
        page: 1,
      }),
    );
  });

  it("重置：清空全部查询条件并重新加载", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "大机";
    vm.query.device_no = "011";
    vm.query.status = "在线";
    await vm.handleReset();
    expect(vm.query.project_id).toBeNull();
    expect(vm.query.name).toBe("");
    expect(vm.query.device_no).toBe("");
    expect(vm.query.status).toBeNull();
    expect(vi.mocked(fetchAntiIntrusionDevices)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 1,
        project_id: undefined,
        name: undefined,
        device_no: undefined,
        status: undefined,
      }),
    );
  });

  it("新增弹窗：默认状态为在线，并继承列表已选项目", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.openCreate();
    expect(vm.form.project_id).toBe(1);
    expect(vm.form.status).toBe("在线");
    expect(vm.form.longitude).toBeUndefined();
  });

  it("编辑弹窗：回填字段（含 SN 与经纬度）", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.tableData[0]);
    expect(vm.form.name).toBe("大机防侵限设备01");
    expect(vm.form.device_no).toBe("011");
    expect(vm.form.sn).toBe("SN001");
    expect(vm.form.longitude).toBe(116.397);
    expect(vm.form.latitude).toBe(39.909);
    expect(vm.buildData()).toMatchObject({
      project_id: 1,
      name: "大机防侵限设备01",
      device_no: "011",
      sn: "SN001",
      longitude: 116.397,
      latitude: 39.909,
      status: "在线",
    });
  });

  it("查看弹窗：空经纬度回填为 undefined，提交时序列化为 null", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openView(vm.tableData[1]);
    expect(vm.form.longitude).toBeUndefined();
    expect(vm.buildData()).toMatchObject({ longitude: null, latitude: null, sn: null });
  });

  it("删除：二次确认文案为「您确认删除当前设备？」", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalledWith(
      "您确认删除当前设备？",
      "删除确认",
      expect.any(Object),
    );
    expect(vi.mocked(deleteAntiIntrusionDevice)).toHaveBeenCalledWith(1);
  });

  it("删除：用户取消时不调用接口", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(deleteAntiIntrusionDevice)).not.toHaveBeenCalled();
  });

  it("批量删除：工具条展示已选条数，未选中时按钮禁用", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const bar = wrapper.find(".batch-actions");
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain("已选择");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeDefined();

    (wrapper.vm as any).onSelectionChange(antiDevices.items);
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".batch-actions").text()).toContain("2");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeUndefined();
  });

  it("批量删除：确认后调用 batchDeleteAntiIntrusionDevices 并重新加载列表", async () => {
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(antiDevices.items);
    vi.mocked(fetchAntiIntrusionDevices).mockClear();

    await vm.onBatchDelete();
    await flushPromises();

    expect(vi.mocked(batchDeleteAntiIntrusionDevices)).toHaveBeenCalledWith([1, 2]);
    expect(vi.mocked(fetchAntiIntrusionDevices)).toHaveBeenCalled();
    expect(vm.selectedRows.length).toBe(0);
  });

  it("接口异常时不抛出且列表保持为空", async () => {
    vi.mocked(fetchAntiIntrusionDevices).mockRejectedValueOnce(new Error("boom"));
    wrapper = mount(AntiIntrusionDeviceListView);
    await flushPromises();
    expect((wrapper.vm as any).tableData.length).toBe(0);
    expect(wrapper.text()).toContain("暂无大机防侵限设备");
  });
});
