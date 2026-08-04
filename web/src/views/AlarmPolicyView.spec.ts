// AlarmPolicyView 单测（🅱 M4 告警策略：加载、权限、新增/编辑提交、删除）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ElMessageBox } from "element-plus";
import AlarmPolicyView from "@/views/AlarmPolicyView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElNotification: vi.fn(),
    ElMessageBox: { confirm: vi.fn() },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: { permission_codes: ["alarm_policy:list", "alarm_policy:manage"] },
    hasPermission: (c: string) => ["alarm_policy:list", "alarm_policy:manage"].includes(c),
    loadProfile: vi.fn(),
  })),
}));

const policies = {
  items: [
    {
      id: 1,
      name: "夜间围栏静默",
      project_id: null,
      project_name: null,
      alarm_type: "fence_intrusion",
      enabled: true,
      suppress_window_seconds: null,
      silence_start: "22:00",
      silence_end: "06:00",
      escalate_after_minutes: 30,
      escalate_to_level: "严重",
      escalate_channels: "in_app",
      note: null,
      created_at: "2026-07-28T09:00:00",
      updated_at: null,
    },
    {
      id: 2,
      name: "设备自报升级",
      project_id: 5,
      project_name: "京张高铁",
      alarm_type: null,
      enabled: false,
      suppress_window_seconds: 600,
      silence_start: null,
      silence_end: null,
      escalate_after_minutes: null,
      escalate_to_level: "警告",
      escalate_channels: "in_app,sms",
      note: "示例",
      created_at: "2026-07-28T10:00:00",
      updated_at: null,
    },
  ],
  total: 2,
  page: 1,
  size: 20,
};

vi.mock("@/api/alarm-policy", () => ({
  batchDeleteAlarmPolicies: vi.fn().mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  listAlarmPolicies: vi.fn(),
  getAlarmPolicyMeta: vi.fn(),
  createAlarmPolicy: vi.fn(),
  updateAlarmPolicy: vi.fn(),
  deleteAlarmPolicy: vi.fn(),
  runEscalations: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));

import {
  createAlarmPolicy,
  deleteAlarmPolicy,
  getAlarmPolicyMeta,
  listAlarmPolicies,
  updateAlarmPolicy,
} from "@/api/alarm-policy";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listAlarmPolicies).mockResolvedValue(policies as any);
  vi.mocked(getAlarmPolicyMeta).mockResolvedValue({
    alarm_types: [{ key: "fence_intrusion", label: "围栏侵入" }],
    levels: ["提示", "警告", "严重"],
    channels: ["in_app", "sms", "voice"],
  } as any);
  vi.mocked(fetchProjects).mockResolvedValue({ items: [{ id: 5, name: "京张高铁" }] } as any);
  vi.mocked(createAlarmPolicy).mockResolvedValue({ id: 3 } as any);
  vi.mocked(updateAlarmPolicy).mockResolvedValue({ id: 1 } as any);
  vi.mocked(deleteAlarmPolicy).mockResolvedValue({ deleted: true } as any);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});

describe("views/AlarmPolicyView.vue", () => {
  it("挂载后加载策略列表与元数据，且 manage 权限命中", async () => {
    wrapper = mount(AlarmPolicyView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vi.mocked(listAlarmPolicies)).toHaveBeenCalled();
    expect(vi.mocked(getAlarmPolicyMeta)).toHaveBeenCalled();
    expect(vm.items.length).toBe(2);
    expect(vm.total).toBe(2);
    expect(vm.canManage).toBe(true);
  });

  it("新增策略：打开对话框并调用 createAlarmPolicy", async () => {
    wrapper = mount(AlarmPolicyView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    vm.form.name = "测试策略";
    vm.form.alarm_type = "";
    await vm.submitForm();
    await flushPromises();
    expect(vi.mocked(createAlarmPolicy)).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(createAlarmPolicy).mock.calls[0][0];
    expect(payload.name).toBe("测试策略");
    expect(payload.project_id).toBeNull();
  });

  it("编辑策略：回显原值并调用 updateAlarmPolicy", async () => {
    wrapper = mount(AlarmPolicyView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.items[0]);
    await flushPromises();
    expect(vm.form.name).toBe("夜间围栏静默");
    expect(vm.editingId).toBe(1);
    await vm.submitForm();
    await flushPromises();
    expect(vi.mocked(updateAlarmPolicy)).toHaveBeenCalledWith(1, expect.objectContaining({ name: "夜间围栏静默" }));
  });

  it("删除策略：确认后调用 deleteAlarmPolicy", async () => {
    wrapper = mount(AlarmPolicyView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.removeRow(vm.items[1]);
    await flushPromises();
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalled();
    expect(vi.mocked(deleteAlarmPolicy)).toHaveBeenCalledWith(2);
  });
});
