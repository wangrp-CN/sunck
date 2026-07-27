// DispatchView 单测（根因派单列表：加载、统计、权限、状态动作、改派）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DispatchView from "@/views/DispatchView.vue";

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
    user: { permission_codes: ["dispatch:list", "dispatch:create", "dispatch:handle"] },
    hasPermission: (c: string) => ["dispatch:list", "dispatch:create", "dispatch:handle"].includes(c),
    loadProfile: vi.fn(),
  })),
}));

const orders = {
  items: [
    {
      id: 1,
      project_id: 1,
      source_type: "correlation",
      source_id: 5,
      title: "多设备同围栏侵入",
      root_cause_hint: "大型机械集中作业",
      level: "严重",
      status: "待派",
      assignee_id: null,
      assignee_name: null,
      deadline: null,
      description: null,
      last_action_note: null,
      closed_at: null,
      created_by: 1,
      created_at: "2026-07-20T09:00:00",
      updated_at: null,
    },
    {
      id: 2,
      project_id: 1,
      source_type: "alarm",
      source_id: 99,
      title: "单点重复告警",
      root_cause_hint: null,
      level: "警告",
      status: "处理中",
      assignee_id: 10,
      assignee_name: "李四",
      deadline: null,
      description: null,
      last_action_note: null,
      closed_at: null,
      created_by: 1,
      created_at: "2026-07-19T09:00:00",
      updated_at: null,
    },
  ],
  total: 2,
  page: 1,
  size: 20,
};

vi.mock("@/api/dispatch", () => ({
  listDispatches: vi.fn(),
  getDispatchStats: vi.fn(),
  getDispatchOptions: vi.fn(),
  dispatchAction: vi.fn(),
  reassignDispatch: vi.fn(),
  createDispatch: vi.fn(),
}));
vi.mock("@/api/user", () => ({ listUsers: vi.fn() }));

import { listUsers } from "@/api/user";
vi.mock("@/components/DispatchCreateDialog.vue", () => ({
  default: { name: "DispatchCreateDialog", template: "<div/>" },
}));

import {
  createDispatch,
  dispatchAction,
  getDispatchOptions,
  getDispatchStats,
  listDispatches,
  reassignDispatch,
} from "@/api/dispatch";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listDispatches).mockResolvedValue(orders as any);
  vi.mocked(getDispatchStats).mockResolvedValue({
    total: 2,
    by_status: { 待派: 1, 处理中: 1, 已闭环: 0 },
    by_level: { 严重: 1, 警告: 1 },
  } as any);
  vi.mocked(getDispatchOptions).mockResolvedValue({
    statuses: ["待派", "处理中", "已闭环"],
    sources: ["correlation", "alarm", "manual"],
    levels: ["严重", "警告", "提示"],
  } as any);
  vi.mocked(listDispatches).mockResolvedValue(orders as any);
});

describe("views/DispatchView.vue", () => {
  it("挂载后加载列表、统计与可选项", async () => {
    wrapper = mount(DispatchView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vi.mocked(listDispatches)).toHaveBeenCalled();
    expect(vi.mocked(getDispatchStats)).toHaveBeenCalled();
    expect(vm.items.length).toBe(2);
    expect(vm.total).toBe(2);
    expect(vm.stats.total).toBe(2);
    expect(vm.options.statuses).toContain("待派");
  });

  it("权限：dispatch:create / dispatch:handle 命中时按钮可见", async () => {
    wrapper = mount(DispatchView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vm.canCreate).toBe(true);
    expect(vm.canHandle).toBe(true);
  });

  it("状态动作：闭环调用 dispatchAction('close') 并刷新", async () => {
    vi.mocked(dispatchAction).mockResolvedValue({ id: 2, status: "已闭环" } as any);
    wrapper = mount(DispatchView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.doAction(vm.items[1], "close");
    await flushPromises();
    expect(vi.mocked(dispatchAction)).toHaveBeenCalledWith(2, "close", undefined);
    expect(vi.mocked(listDispatches)).toHaveBeenCalledTimes(2); // 初始 + 动作后刷新
  });

  it("改派：确认后调用 reassignDispatch", async () => {
    vi.mocked(reassignDispatch).mockResolvedValue({ id: 2, status: "处理中", assignee_id: 20 } as any);
    vi.mocked(listUsers).mockResolvedValue({ items: [{ id: 20, nickname: "王五", username: "ww" }] } as any);
    wrapper = mount(DispatchView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.openReassign(vm.items[1]);
    vm.reassignUserId = 20;
    await vm.submitReassign();
    await flushPromises();
    expect(vi.mocked(reassignDispatch)).toHaveBeenCalledWith(2, 20, undefined);
  });
});
