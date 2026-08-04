// PlaybookView 单测（🅱 M5 处置预案/知识库联动：加载、权限、新增/编辑提交、删除）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ElMessageBox } from "element-plus";
import PlaybookView from "@/views/PlaybookView.vue";

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
    user: { permission_codes: ["playbook:list", "playbook:manage"] },
    hasPermission: (c: string) => ["playbook:list", "playbook:manage"].includes(c),
    loadProfile: vi.fn(),
  })),
}));

const playbooks = {
  items: [
    {
      id: 1,
      name: "电子围栏侵入处置预案",
      project_id: null,
      project_name: null,
      alarm_type: "fence_intrusion",
      alarm_level: "严重",
      enabled: true,
      summary: "现场核实并处置",
      steps: ["1. 调阅视频", "2. 通知现场"],
      trigger_condition: null,
      references: [{ title: "安全细则", url: "https://example.com/kb" }],
      tags: "围栏,侵入",
      owner_role: "现场安全员",
      est_minutes: 15,
      note: null,
      created_at: "2026-07-30T09:00:00",
      updated_at: null,
    },
    {
      id: 2,
      name: "设备自报告警处置预案",
      project_id: 5,
      project_name: "京张高铁",
      alarm_type: "device_alarm",
      alarm_level: null,
      enabled: false,
      summary: "判定故障并派单",
      steps: ["1. 查看状态"],
      trigger_condition: null,
      references: [],
      tags: null,
      owner_role: null,
      est_minutes: null,
      note: "示例",
      created_at: "2026-07-30T10:00:00",
      updated_at: null,
    },
  ],
  total: 2,
  page: 1,
  size: 20,
};

vi.mock("@/api/playbook", () => ({
  batchDeletePlaybooks: vi.fn().mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  listPlaybooks: vi.fn(),
  getPlaybookMeta: vi.fn(),
  createPlaybook: vi.fn(),
  updatePlaybook: vi.fn(),
  deletePlaybook: vi.fn(),
  recommendPlaybooks: vi.fn(),
  recommendPlaybooksByAlarm: vi.fn(),
}));
vi.mock("@/api/knowledge", () => ({
  searchKnowledge: vi.fn(),
}));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));

import {
  createPlaybook,
  deletePlaybook,
  getPlaybookMeta,
  listPlaybooks,
  updatePlaybook,
} from "@/api/playbook";
import { searchKnowledge } from "@/api/knowledge";
import { fetchProjects } from "@/api/project";

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPlaybooks).mockResolvedValue(playbooks as any);
  vi.mocked(getPlaybookMeta).mockResolvedValue({
    alarm_types: [{ key: "fence_intrusion", label: "围栏侵入" }],
    levels: ["提示", "警告", "严重"],
  } as any);
  vi.mocked(fetchProjects).mockResolvedValue({ items: [{ id: 5, name: "京张高铁" }] } as any);
  vi.mocked(createPlaybook).mockResolvedValue({ id: 3 } as any);
  vi.mocked(updatePlaybook).mockResolvedValue({ id: 1 } as any);
  vi.mocked(deletePlaybook).mockResolvedValue({ deleted: true } as any);
  vi.mocked(ElMessageBox.confirm).mockResolvedValue("confirm" as any);
});

describe("views/PlaybookView.vue", () => {
  it("挂载后加载预案列表与元数据，且 manage 权限命中", async () => {
    wrapper = mount(PlaybookView);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vi.mocked(listPlaybooks)).toHaveBeenCalled();
    expect(vi.mocked(getPlaybookMeta)).toHaveBeenCalled();
    expect(vm.items.length).toBe(2);
    expect(vm.total).toBe(2);
    expect(vm.canManage).toBe(true);
  });

  it("新增预案：打开对话框、添加步骤与链接并调用 createPlaybook", async () => {
    wrapper = mount(PlaybookView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    vm.form.name = "测试预案";
    vm.form.summary = "处置要点";
    vm.form.stepDraft = "1. 第一步";
    vm.addStep();
    vm.form.refTitle = "手册";
    vm.form.refUrl = "https://example.com/m";
    vm.addRef();
    await vm.submitForm();
    await flushPromises();
    expect(vi.mocked(createPlaybook)).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(createPlaybook).mock.calls[0][0];
    expect(payload.name).toBe("测试预案");
    expect(payload.steps).toEqual(["1. 第一步"]);
    expect(payload.references).toEqual([{ title: "手册", url: "https://example.com/m" }]);
  });

  it("编辑预案：回显原值并调用 updatePlaybook", async () => {
    wrapper = mount(PlaybookView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openEdit(vm.items[0]);
    await flushPromises();
    expect(vm.form.name).toBe("电子围栏侵入处置预案");
    expect(vm.editingId).toBe(1);
    await vm.submitForm();
    await flushPromises();
    expect(vi.mocked(updatePlaybook)).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ name: "电子围栏侵入处置预案" }),
    );
  });

  it("删除预案：确认后调用 deletePlaybook", async () => {
    wrapper = mount(PlaybookView);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.removeRow(vm.items[1]);
    await flushPromises();
    expect(vi.mocked(ElMessageBox.confirm)).toHaveBeenCalled();
    expect(vi.mocked(deletePlaybook)).toHaveBeenCalledWith(2);
  });

  it("从知识库检索关联链接：检索结果可加入预案 references", async () => {
    wrapper = mount(PlaybookView);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.openCreate();
    vm.form.name = "围栏处置";
    vi.mocked(searchKnowledge).mockResolvedValue([
      {
        id: 10,
        title: "防护栅栏管理办法",
        url: "https://kb.example.com/fence",
        summary: "现场处置要点",
        source: "规范库",
        tags: "围栏",
        content: null,
        project_id: null,
        project_name: null,
        enabled: true,
        created_at: null,
        updated_at: null,
        score: 5,
      },
    ] as any);
    vm.openKbSearch();
    expect(vm.kbDialogVisible).toBe(true);
    await vm.runKbSearch();
    await flushPromises();
    expect(vm.kbResults.length).toBe(1);
    vm.addKbOne(vm.kbResults[0]);
    expect(vm.form.references.some((r: any) => r.url === "https://kb.example.com/fence")).toBe(
      true,
    );
  });
});
