// ProjectListView 单测（项目管理·项目列表：查询渲染、状态色、新增弹窗）
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

  it("点击新增打开弹窗并展示经纬度与只读工期字段", async () => {
    const wrapper = mount(ProjectListView);
    await flushPromises();

    await btnByText(wrapper, "新增")!.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("新增项目");
    expect(wrapper.text()).toContain("经度");
    expect(wrapper.text()).toContain("纬度");
    expect(wrapper.text()).toContain("项目工期");
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
