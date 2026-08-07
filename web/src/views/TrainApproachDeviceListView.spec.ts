// TrainApproachDeviceListView 单测（列车接近报警设备列表：查询/重置/权限/弹窗/删除/批量删除）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TrainApproachDeviceListView from "@/views/TrainApproachDeviceListView.vue";
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
      "train_approach_device:list",
      "train_approach_device:add",
      "train_approach_device:edit",
      "train_approach_device:delete",
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

const trainDevices = {
  items: [
    {
      id: 1,
      project_id: 1,
      project_name: "项目A",
      name: "列车接近报警设备01",
      device_no: "011",
      sn: "SN001",
      direction: "上行",
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
      name: "列车接近报警设备02",
      device_no: "012",
      sn: null,
      direction: null,
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

vi.mock("@/api/trainApproachDevice", () => ({
  batchDeleteTrainApproachDevices: vi
    .fn()
    .mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  fetchTrainApproachDevices: vi.fn(),
  fetchTrainApproachDevice: vi.fn(),
  createTrainApproachDevice: vi.fn(),
  updateTrainApproachDevice: vi.fn(),
  deleteTrainApproachDevice: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));

import {
  batchDeleteTrainApproachDevices,
  deleteTrainApproachDevice,
  fetchTrainApproachDevices,
} from "@/api/trainApproachDevice";
import { fetchProjects } from "@/api/project";
import { TRAIN_APPROACH_DEVICE_DIRECTIONS } from "@/types";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchTrainApproachDevices).mockResolvedValue(trainDevices as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: 1, name: "项目A" }],
    total: 1,
  } as any);
  vi.mocked(deleteTrainApproachDevice).mockResolvedValue(null);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/TrainApproachDeviceListView.vue", () => {
  it("挂载后加载设备列表与项目并渲染表格", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    expect(vi.mocked(fetchTrainApproachDevices)).toHaveBeenCalled();
    expect((wrapper.vm as any).tableData.length).toBe(2);
    expect(wrapper.text()).toContain("列车接近报警设备01");
    expect(wrapper.text()).toContain("项目A");
  });

  it("渲染原型定义的列头与操作入口", async () => {
    wrapper = mount(TrainApproachDeviceListView);
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
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "列车";
    vm.query.device_no = "011";
    vm.query.status = "在线";
    await vm.handleSearch();
    expect(vi.mocked(fetchTrainApproachDevices)).toHaveBeenLastCalledWith(
      expect.objectContaining({
        project_id: 1,
        name: "列车",
        device_no: "011",
        status: "在线",
        page: 1,
      }),
    );
  });

  it("重置：清空全部查询条件并重新加载", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.query.name = "列车";
    vm.query.device_no = "011";
    vm.query.status = "在线";
    await vm.handleReset();
    expect(vm.query.project_id).toBeNull();
    expect(vm.query.name).toBe("");
    expect(vm.query.device_no).toBe("");
    expect(vm.query.status).toBeNull();
    expect(vi.mocked(fetchTrainApproachDevices)).toHaveBeenLastCalledWith(
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
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.query.project_id = 1;
    vm.openCreate();
    expect(vm.form.project_id).toBe(1);
    expect(vm.form.status).toBe("在线");
    expect(vm.form.longitude).toBeUndefined();
  });

  it("编辑弹窗：回填字段（含 SN / 方位 / 经纬度）", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.tableData[0]);
    expect(vm.form.name).toBe("列车接近报警设备01");
    expect(vm.form.device_no).toBe("011");
    expect(vm.form.sn).toBe("SN001");
    expect(vm.form.direction).toBe("上行");
    expect(vm.form.longitude).toBe(116.397);
    expect(vm.form.latitude).toBe(39.909);
    expect(vm.buildData()).toMatchObject({
      project_id: 1,
      name: "列车接近报警设备01",
      device_no: "011",
      sn: "SN001",
      direction: "上行",
      longitude: 116.397,
      latitude: 39.909,
      status: "在线",
    });
  });

  it("查看弹窗：空方位/经纬度回填为空，提交时序列化为 null", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openView(vm.tableData[1]);
    expect(vm.form.longitude).toBeUndefined();
    expect(vm.form.direction).toBe("");
    expect(vm.buildData()).toMatchObject({
      longitude: null,
      latitude: null,
      sn: null,
      direction: null,
    });
  });

  it("删除：二次确认文案为「您确认删除当前设备？」", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalledWith(
      "您确认删除当前设备？",
      "删除确认",
      expect.any(Object),
    );
    expect(vi.mocked(deleteTrainApproachDevice)).toHaveBeenCalledWith(1);
  });

  it("删除：用户取消时不调用接口", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    await vm.handleDelete(vm.tableData[0]);
    expect(vi.mocked(deleteTrainApproachDevice)).not.toHaveBeenCalled();
  });

  it("批量删除：工具条展示已选条数，未选中时按钮禁用", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const bar = wrapper.find(".batch-actions");
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain("已选择");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeDefined();

    (wrapper.vm as any).onSelectionChange(trainDevices.items);
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".batch-actions").text()).toContain("2");
    expect(wrapper.find(".batch-actions__delete").attributes("disabled")).toBeUndefined();
  });

  it("批量删除：确认后调用 batchDeleteTrainApproachDevices 并重新加载列表", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.onSelectionChange(trainDevices.items);
    vi.mocked(fetchTrainApproachDevices).mockClear();

    await vm.onBatchDelete();
    await flushPromises();

    expect(vi.mocked(batchDeleteTrainApproachDevices)).toHaveBeenCalledWith([1, 2]);
    expect(vi.mocked(fetchTrainApproachDevices)).toHaveBeenCalled();
    expect(vm.selectedRows.length).toBe(0);
  });

  it("接口异常时不抛出且列表保持为空", async () => {
    vi.mocked(fetchTrainApproachDevices).mockRejectedValueOnce(new Error("boom"));
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    expect((wrapper.vm as any).tableData.length).toBe(0);
    expect(wrapper.text()).toContain("暂无列车接近报警设备");
  });

  it("设备方位下拉选项固定为上行/下行", () => {
    expect(TRAIN_APPROACH_DEVICE_DIRECTIONS).toEqual(["上行", "下行"]);
  });

  it("设备方位为必填项（表单校验规则含 required）", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const rules = (wrapper.vm as any).rules;
    expect(Array.isArray(rules.direction)).toBe(true);
    expect(rules.direction.some((r: any) => r.required === true)).toBe(true);
  });

  it("新增弹窗：设备方位默认空，提交时序列化为 null（必填校验拦截）", async () => {
    wrapper = mount(TrainApproachDeviceListView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    expect(vm.form.direction).toBe("");
    expect(vm.buildData()).toMatchObject({ direction: null });
  });
});
