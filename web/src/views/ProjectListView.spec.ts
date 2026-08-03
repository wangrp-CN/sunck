// ProjectListView 单测（项目管理·项目列表：查询渲染、状态色、新增弹窗）
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createProject } from "@/api/project";
import ProjectListView from "@/views/ProjectListView.vue";

const hoist = vi.hoisted(() => {
  const sample = {
    id: 1,
    name: "XX涉铁工程",
    short_name: "XX",
    dept_id: 10,
    intro: "重点涉铁施工项目",
    start_date: "2026-01-01",
    end_date: "2026-06-01",
    duration: 151,
    mileage: "3km",
    section: "K1~K2",
    coordinate: "116.4,39.9",
    status: "在建" as const,
    created_by: 1,
    created_at: "2026-01-02 10:00:00",
  };
  return { sample };
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
  useAuthStore: vi.fn(() => ({
    user: {
      permission_codes: ["project:list", "project:add", "project:edit", "project:delete"],
    },
    loadProfile: vi.fn(),
  })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/projects/list", meta: {}, query: {} }),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: vi.fn().mockResolvedValue({
    items: [hoist.sample],
    total: 1,
    page: 1,
    size: 20,
  }),
  createProject: vi.fn().mockResolvedValue(hoist.sample),
  updateProject: vi.fn().mockResolvedValue(hoist.sample),
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

  it("渲染查询区、列表与状态标签（在建=蓝 tag）", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("项目名称");
    expect(text).toContain("项目状态");
    expect(text).toContain("查询");
    expect(text).toContain("重置");
    expect(text).toContain("新增");
    // 列表数据
    expect(text).toContain("XX涉铁工程");
    expect(text).toContain("重点涉铁施工项目");
    expect(text).toContain("151 天");
    // 状态标签
    expect(text).toContain("在建");
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
    expect(wrapper.text()).toContain("XX涉铁工程");
    // 查看态：保存按钮不应出现
    expect(btnByText(wrapper, "保存")).toBeUndefined();
  });
});
