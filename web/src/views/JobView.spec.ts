// JobView 单测（作业计划管理 · 作业列表：查询/排序/状态提示/三步向导/删除确认）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobView from "@/views/JobView.vue";
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
    const permission_codes = ["job:add", "job:edit", "job:delete"];
    return {
      user: { permission_codes },
      hasPermission: (code: string) => permission_codes.includes(code),
      loadProfile: vi.fn(),
    };
  }),
}));

vi.mock("@/api/job", () => ({
  fetchJobs: vi.fn(),
  fetchJob: vi.fn(),
  createJob: vi.fn(),
  updateJob: vi.fn(),
  deleteJob: vi.fn(),
  cloneJob: vi.fn(),
  saveJobAsTemplate: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("@/api/person", () => ({ fetchPersons: vi.fn() }));
vi.mock("@/api/machine", () => ({ fetchMachines: vi.fn() }));
vi.mock("@/api/fence", () => ({ fetchFences: vi.fn() }));
vi.mock("@/api/device", () => ({ fetchDevices: vi.fn() }));

import { createJob, deleteJob, fetchJob, fetchJobs } from "@/api/job";
import { fetchProjects } from "@/api/project";
import { fetchPersons } from "@/api/person";
import { fetchMachines } from "@/api/machine";
import { fetchFences } from "@/api/fence";
import { fetchDevices } from "@/api/device";

const jobRow = {
  id: 7,
  project_id: 1,
  project_name: "京广高铁改造",
  name: "夜间道砟更换",
  is_start: true,
  description: "K120+300 至 K120+800 区间",
  plan_time: "2026-08-05 22:00:00~2026-08-06 04:00:00",
  plan_start: "2026-08-05T22:00:00",
  plan_end: "2026-08-06T04:00:00",
  status: "执行中",
  created_at: "2026-08-04 09:00:00",
};

const jobDetail = {
  ...jobRow,
  person_bindings: [
    { person_id: 11, person_name: "张三", person_no: "P001", device_no: "L-01", device_name: "定位卡01" },
  ],
  machine_bindings: [
    {
      machine_id: 21,
      machine_no: "DJ-01",
      guard_person_id: 11,
      guard_person_name: "张三",
      driver_person_id: 12,
      driver_person_name: "李四",
      arm_device_no: "A-01",
      body_device_no: "A-02",
      voice_device_no: "V-01",
    },
  ],
  fence_rules: [
    {
      fence_id: 31,
      fence_name: "作业区围栏",
      monitor_target: "计划外人员",
      trigger_condition: "进入",
      time_range: "22:00:00~04:00:00",
      dwell_time: 5,
    },
  ],
};

const page = <T>(items: T[]) => ({ items, total: items.length, page: 1, size: 10 });

let wrapper: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchJobs).mockResolvedValue(page([jobRow]) as never);
  vi.mocked(fetchJob).mockResolvedValue(jobDetail as never);
  vi.mocked(createJob).mockResolvedValue(jobDetail as never);
  vi.mocked(deleteJob).mockResolvedValue(null as never);
  vi.mocked(fetchProjects).mockResolvedValue(page([{ id: 1, name: "京广高铁改造" }]) as never);
  vi.mocked(fetchPersons).mockResolvedValue(
    page([
      { id: 11, name: "张三", person_no: "P001", project_id: 1 },
      { id: 12, name: "李四", person_no: "P002", project_id: 1 },
    ]) as never,
  );
  vi.mocked(fetchMachines).mockResolvedValue(
    page([{ id: 21, machine_no: "DJ-01", machine_type: "捣固车", project_id: 1 }]) as never,
  );
  vi.mocked(fetchFences).mockResolvedValue(
    page([{ id: 31, name: "作业区围栏", project_id: 1 }]) as never,
  );
  vi.mocked(fetchDevices).mockResolvedValue(
    page([
      { id: 41, device_no: "L-01", name: "定位卡01", device_type: "locate", project_id: 1 },
      { id: 42, device_no: "A-01", name: "前臂防侵限", device_type: "anti_intrusion", project_id: 1 },
      { id: 43, device_no: "V-01", name: "车载语音", device_type: "train_approach", project_id: 1 },
    ]) as never,
  );
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as never);
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/JobView.vue", () => {
  it("挂载后加载项目与计划列表，默认创建时间倒序", async () => {
    wrapper = mount(JobView);
    await flushPromises();
    expect(vi.mocked(fetchProjects)).toHaveBeenCalled();
    expect(vi.mocked(fetchJobs)).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: "created_at", order: "desc", page: 1, size: 10 }),
    );
    expect(wrapper.text()).toContain("夜间道砟更换");
    expect(wrapper.text()).toContain("京广高铁改造");
    // 状态按原型口径展示：执行中 → 进行中；启动标记
    expect(wrapper.text()).toContain("进行中");
    expect(wrapper.text()).toContain("启动");
  });

  it("多条件查询带参并回到第 1 页", async () => {
    wrapper = mount(JobView);
    await flushPromises();
    const vm = wrapper.vm as never as {
      filters: { keyword: string; status: string; is_start?: boolean; project_id: number | null };
      page: number;
      handleSearch: () => void;
    };
    vm.page = 3;
    vm.filters.keyword = " 道砟 ";
    vm.filters.status = "执行中";
    vm.filters.is_start = true;
    vm.filters.project_id = 1;
    vi.mocked(fetchJobs).mockClear();
    vm.handleSearch();
    await flushPromises();
    expect(vi.mocked(fetchJobs)).toHaveBeenCalledWith(
      expect.objectContaining({
        keyword: "道砟",
        status: "执行中",
        is_start: true,
        project_id: 1,
        page: 1,
      }),
    );
  });

  it("点击表头排序会带 sort_by / order 重新查询，取消排序回落创建时间倒序", async () => {
    wrapper = mount(JobView);
    await flushPromises();
    const vm = wrapper.vm as never as {
      handleSortChange: (p: { prop: string | null; order: string | null }) => void;
    };
    vi.mocked(fetchJobs).mockClear();
    vm.handleSortChange({ prop: "plan_start", order: "ascending" });
    await flushPromises();
    expect(vi.mocked(fetchJobs)).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: "plan_start", order: "asc" }),
    );
    vm.handleSortChange({ prop: null, order: null });
    await flushPromises();
    expect(vi.mocked(fetchJobs)).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: "created_at", order: "desc" }),
    );
  });

  it("请求失败时提示错误并可重试；空数据展示空态", async () => {
    vi.mocked(fetchJobs).mockRejectedValueOnce(new Error("网络异常"));
    wrapper = mount(JobView);
    await flushPromises();
    expect(wrapper.text()).toContain("网络异常");
    expect(wrapper.text()).toContain("重试");

    // 重试成功后错误提示消失
    vi.mocked(fetchJobs).mockResolvedValueOnce(page([]) as never);
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "重试")
      ?.trigger("click");
    await flushPromises();
    expect(wrapper.text()).not.toContain("网络异常");
    expect(wrapper.text()).toContain("暂无作业计划");
  });

  it("删除需二次确认，确认后调用接口并刷新", async () => {
    wrapper = mount(JobView);
    await flushPromises();
    const vm = wrapper.vm as never as { handleDelete: (r: unknown) => Promise<void> };
    await vm.handleDelete(jobRow);
    await flushPromises();
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalledWith(
      "您确认删除当前作业计划？",
      "删除确认",
      expect.any(Object),
    );
    expect(vi.mocked(deleteJob)).toHaveBeenCalledWith(7);
  });

  it("取消二次确认时不调用删除接口", async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce(new Error("cancel"));
    wrapper = mount(JobView);
    await flushPromises();
    const vm = wrapper.vm as never as { handleDelete: (r: unknown) => Promise<void> };
    await vm.handleDelete(jobRow);
    await flushPromises();
    expect(vi.mocked(deleteJob)).not.toHaveBeenCalled();
  });

  it("新增向导：默认启动、行式绑定校验并提交结构化 payload", async () => {
    wrapper = mount(JobView);
    await flushPromises();
    const vm = wrapper.vm as never as {
      openCreate: () => Promise<void>;
      form: Record<string, unknown>;
      personDraft: { person_id: number | null; device_no: string | null };
      addPersonRow: () => void;
      personRows: unknown[];
      machineDraft: Record<string, unknown>;
      addMachineRow: () => void;
      machineRows: unknown[];
      fenceDraft: Record<string, unknown>;
      fenceTimeRange: string[];
      addFenceRow: () => void;
      fenceRows: unknown[];
      submitWizard: () => Promise<void>;
    };
    await vm.openCreate();
    await flushPromises();
    expect(vm.form.is_start).toBe(true); // 原型：计划启动默认「启动」
    expect(vi.mocked(fetchPersons)).toHaveBeenCalled();
    expect(vi.mocked(fetchDevices)).toHaveBeenCalledTimes(3);

    vm.form.project_id = 1;
    vm.form.name = "夜间道砟更换";
    vm.form.plan_range = ["2026-08-05 22:00:00", "2026-08-06 04:00:00"];

    // 人员行：缺设备不入表
    vm.personDraft.person_id = 11;
    vm.addPersonRow();
    expect(vm.personRows.length).toBe(0);
    vm.personDraft.device_no = "L-01";
    vm.addPersonRow();
    expect(vm.personRows.length).toBe(1);
    // 同一人员不可重复添加
    vm.personDraft.person_id = 11;
    vm.personDraft.device_no = "L-01";
    vm.addPersonRow();
    expect(vm.personRows.length).toBe(1);

    // 大机行：防护/驾驶人员必填
    vm.machineDraft.machine_id = 21;
    vm.addMachineRow();
    expect(vm.machineRows.length).toBe(0);
    vm.machineDraft.guard_person_id = 11;
    vm.machineDraft.driver_person_id = 12;
    vm.machineDraft.arm_device_no = "A-01";
    vm.machineDraft.voice_device_no = "V-01";
    vm.addMachineRow();
    expect(vm.machineRows.length).toBe(1);

    // 围栏规则行：时间范围拼成 HH:mm:ss~HH:mm:ss
    vm.fenceDraft.fence_id = 31;
    vm.fenceDraft.monitor_target = "计划外人员";
    vm.fenceDraft.dwell_time = 5;
    vm.fenceTimeRange = ["22:00:00", "04:00:00"];
    vm.addFenceRow();
    expect(vm.fenceRows.length).toBe(1);

    await vm.submitWizard();
    await flushPromises();
    expect(vi.mocked(createJob)).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(createJob).mock.calls[0][0] as Record<string, unknown>;
    expect(payload.name).toBe("夜间道砟更换");
    expect(payload.is_start).toBe(true);
    expect(payload.person_bindings).toEqual([{ person_id: 11, device_no: "L-01" }]);
    expect(payload.machine_bindings).toEqual([
      expect.objectContaining({ machine_id: 21, guard_person_id: 11, driver_person_id: 12 }),
    ]);
    expect(payload.fence_rules).toEqual([
      expect.objectContaining({
        fence_id: 31,
        monitor_target: "计划外人员",
        trigger_condition: "进入",
        time_range: "22:00:00~04:00:00",
        dwell_time: 5,
      }),
    ]);
  });

  it("查看详情回显人员/大机/围栏三段绑定", async () => {
    wrapper = mount(JobView);
    await flushPromises();
    const vm = wrapper.vm as never as { openDetail: (r: unknown) => Promise<void> };
    await vm.openDetail(jobRow);
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
    await flushPromises();
    expect(vi.mocked(fetchJob)).toHaveBeenCalledWith(7);
    const html = wrapper.html() + document.body.innerHTML;
    expect(html).toContain("张三");
    expect(html).toContain("DJ-01");
    expect(html).toContain("作业区围栏");
    expect(html).toContain("计划外人员");
  });
});
