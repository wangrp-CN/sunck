// ProjectListView 单测（项目管理·项目列表：查询渲染、状态色、新增弹窗）
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createProject } from "@/api/project";
import ProjectListView from "@/views/ProjectListView.vue";

const hoist = vi.hoisted(() => {
  const make = (
    id: number,
    name: string,
    status: "在建" | "停工" | "竣工",
    duration: number,
  ) => ({
    id,
    name,
    short_name: name.slice(0, 2),
    dept_id: 10,
    intro: `${name}介绍`,
    start_date: "2026-01-01",
    end_date: "2026-06-01",
    duration,
    mileage: "3km",
    section: "K1~K2",
    coordinate: "116.4,39.9",
    status,
    created_by: 1,
    created_at: "2026-01-02 10:00:00",
  });
  // 测试数据：在建 1 条、停工 2 条、竣工 2 条，用于验证展示与筛选
  const allProjects = [
    make(1, "XX在建工程", "在建", 151),
    make(2, "XX停工工程A", "停工", 60),
    make(3, "XX停工工程B", "停工", 80),
    make(4, "XX竣工工程A", "竣工", 200),
    make(5, "XX竣工工程B", "竣工", 180),
  ];
  return { allProjects };
});

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => {
    const permission_codes = ["project:list", "project:add", "project:edit", "project:delete"];
    return {
      user: { permission_codes, is_superuser: false },
      hasPermission: (code: string) => permission_codes.includes(code),
      loadProfile: vi.fn(),
    };
  }),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/projects/list", meta: {}, query: {} }),
}));

vi.mock("@/api/project", () => ({
  batchDeleteProjects: vi.fn().mockResolvedValue({ deleted: 1, total: 1, skipped: 0 }),
  fetchProjects: vi.fn().mockImplementation(async (params?: Record<string, unknown>) => {
    const status = params?.status as string | undefined;
    const items = status
      ? hoist.allProjects.filter((p) => p.status === status)
      : hoist.allProjects;
    return { items, total: items.length, page: (params?.page as number) ?? 1, size: (params?.size as number) ?? 20 };
  }),
  createProject: vi.fn().mockResolvedValue(hoist.allProjects[0]),
  updateProject: vi.fn().mockResolvedValue(hoist.allProjects[0]),
  deleteProject: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/department", () => ({
  fetchDepartments: vi.fn().mockResolvedValue([
    { id: 10, name: "工程一部", code: "D10", parent_id: null, leader: null, phone: null, sort: 0, status: true, remark: null, created_at: null },
  ]),
  fetchDepartmentTree: vi.fn().mockResolvedValue([
    { id: 10, name: "工程一部", code: "D10", parent_id: null, leader: null, phone: null, sort: 0, status: true, remark: null, created_at: null, children: [] },
  ]),
}));

function btnByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll("button").find((b) => b.text().includes(text));
}

describe("ProjectListView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("渲染查询区、表头（含项目周期（日））、5 行数据，且已移除项目介绍列", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("项目名称");
    expect(text).toContain("项目状态");
    expect(text).toContain("项目周期（日）");
    expect(text).toContain("查询");
    expect(text).toContain("重置");
    expect(text).toContain("新增");
    // 已移除「项目介绍」列：表头与单元格均不应出现介绍内容
    expect(text).not.toContain("项目介绍");
    expect(text).not.toContain("XX在建工程介绍");
    // 列表数据（5 条测试数据：在建/停工/竣工）
    expect(text).toContain("XX在建工程");
    expect(text).toContain("151 天");
    expect(text).toContain("在建");
    expect(text).toContain("停工");
    expect(text).toContain("竣工");
    // 行数 = 5
    expect(wrapper.findAll(".el-table__row").length).toBe(5);
  });

  it("按项目状态筛选：停工/竣工 仅展示对应记录", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();
    const vm = wrapper.vm as unknown as { query: Record<string, unknown> };

    // 筛选「停工」
    vm.query.status = "停工";
    await nextTick();
    await btnByText(wrapper, "查询")!.trigger("click");
    await flushPromises();
    let rows = wrapper.findAll(".el-table__row");
    expect(rows.length).toBe(2);
    rows.forEach((r) => expect(r.text()).toContain("停工"));
    expect(wrapper.text()).not.toContain("XX竣工工程A");

    // 筛选「竣工」
    vm.query.status = "竣工";
    await nextTick();
    await btnByText(wrapper, "查询")!.trigger("click");
    await flushPromises();
    rows = wrapper.findAll(".el-table__row");
    expect(rows.length).toBe(2);
    rows.forEach((r) => expect(r.text()).toContain("竣工"));

    // 重置后恢复全部 5 条
    await btnByText(wrapper, "重置")!.trigger("click");
    await flushPromises();
    expect(wrapper.findAll(".el-table__row").length).toBe(5);
  });

  it("点击新增打开弹窗并展示坐标与只读工期字段", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();

    await btnByText(wrapper, "新增")!.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("新增项目");
    expect(wrapper.text()).toContain("坐标");
    expect(wrapper.text()).toContain("项目工期");
  });

  it("新增表单对必填项与坐标格式做基本校验，并以结构化对象提交", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();
    await btnByText(wrapper, "新增")!.trigger("click");
    await flushPromises();

    const createMock = createProject as ReturnType<typeof vi.fn>;
    createMock.mockClear();

    // 直接提交空表单：必填校验应阻断，不调用接口
    await btnByText(wrapper, "保存")!.trigger("click");
    await flushPromises();
    expect(createMock).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("项目名称");

    // 通过暴露的 form 填写合法数据（日期早于完工，触发工期计算与结构化对象）
    const vm = wrapper.vm as unknown as { form: Record<string, unknown> };
    vm.form.name = "测试项目A";
    vm.form.short_name = "A";
    vm.form.intro = "介绍内容";
    vm.form.coordinate = "116.397,39.909";
    vm.form.dept_id = 10;
    vm.form.start_date = "2026-01-01";
    vm.form.end_date = "2026-06-01";
    await nextTick();

    await btnByText(wrapper, "保存")!.trigger("click");
    await flushPromises();
    expect(createMock).toHaveBeenCalledTimes(1);
    const payload = createMock.mock.calls[0][0];
    // 结构化对象字段校验
    expect(payload.name).toBe("测试项目A");
    expect(payload.short_name).toBe("A");
    expect(payload.intro).toBe("介绍内容");
    expect(payload.coordinate).toBe("116.397,39.909");
    expect(payload.dept_id).toBe(10);
    expect(payload.start_date).toBe("2026-01-01");
    expect(payload.end_date).toBe("2026-06-01");
    expect(payload.status).toBe("在建");
    // 坐标格式非法时也应被阻断
    createMock.mockClear();
    vm.form.coordinate = "not-a-coord";
    await btnByText(wrapper, "保存")!.trigger("click");
    await flushPromises();
    expect(createMock).not.toHaveBeenCalled();
  });

  it("点击查看打开只读详情弹窗且不显示保存按钮", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();

    // 列表首行「查看」按钮
    const viewBtn = wrapper
      .findAll("button")
      .find((b) => b.text().includes("查看"));
    await viewBtn!.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("项目详情");
    expect(wrapper.text()).toContain("XX在建工程");
    // 查看态：保存按钮不应出现
    expect(btnByText(wrapper, "保存")).toBeUndefined();
  });
});
