// 报告订阅页面单测 (#①·定期订阅推送)：渲染、列表加载、新建、删除
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import SubscriptionView from "@/views/SubscriptionView.vue";

const hoisted = vi.hoisted(() => ({
  listSubscriptions: vi.fn(),
  createSubscription: vi.fn(),
  updateSubscription: vi.fn(),
  deleteSubscription: vi.fn(),
  triggerSubscription: vi.fn(),
  downloadSubscription: vi.fn(),
  fetchProjects: vi.fn(),
  authUser: { is_superuser: true, permission_codes: [] as string[] },
}));

vi.mock("@/api/subscriptions", () => ({
  listSubscriptions: (...a: any[]) => hoisted.listSubscriptions(...a),
  createSubscription: (...a: any[]) => hoisted.createSubscription(...a),
  updateSubscription: (...a: any[]) => hoisted.updateSubscription(...a),
  deleteSubscription: (...a: any[]) => hoisted.deleteSubscription(...a),
  triggerSubscription: (...a: any[]) => hoisted.triggerSubscription(...a),
  downloadSubscription: (...a: any[]) => hoisted.downloadSubscription(...a),
}));

vi.mock("@/api/project", () => ({
  fetchProjects: (...a: any[]) => hoisted.fetchProjects(...a),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({ user: hoisted.authUser, loadProfile: vi.fn() })),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: "/intelligence/subscriptions", meta: { title: "报告订阅" } }),
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
    ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) },
  };
});

function clickByText(wrapper: any, text: string) {
  const btn = wrapper
    .findAll("button")
    .find((b: any) => (b.text() as string).includes(text));
  if (!btn) throw new Error(`button not found: ${text}`);
  return btn;
}

const SAMPLE_SUB = {
  id: 11,
  user_id: 1,
  name: "周报A",
  fmt: "excel",
  days: 30,
  project_id: null,
  frequency: "daily",
  send_hour: 8,
  send_weekday: 0,
  send_day: 1,
  channels: ["in_app"],
  enabled: true,
  last_run_at: null,
  last_status: null,
  last_error: null,
  created_at: null,
  updated_at: null,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("SubscriptionView", () => {
  it("renders page title and loads subscription list", async () => {
    hoisted.listSubscriptions.mockResolvedValue([SAMPLE_SUB]);
    hoisted.fetchProjects.mockResolvedValue({ items: [], total: 0, page: 1, size: 200 });

    const wrapper = mount(SubscriptionView);
    await flushPromises();

    expect(wrapper.text()).toContain("报告订阅");
    expect(hoisted.listSubscriptions).toHaveBeenCalled();
    expect(wrapper.text()).toContain("周报A");
  });

  it("superuser can create a subscription via dialog", async () => {
    hoisted.listSubscriptions.mockResolvedValue([]);
    hoisted.fetchProjects.mockResolvedValue({ items: [], total: 0, page: 1, size: 200 });
    hoisted.createSubscription.mockResolvedValue({ ...SAMPLE_SUB, id: 12, name: "新订阅" });

    const wrapper = mount(SubscriptionView);
    await flushPromises();

    clickByText(wrapper, "新建订阅").trigger("click");
    await flushPromises();

    (wrapper.vm as any).form.name = "新订阅";
    await flushPromises();

    // 对话框 append-to-body 渲染在 wrapper 外，直接调用组件方法触发保存
    await (wrapper.vm as any).save();
    await flushPromises();

    expect(hoisted.createSubscription).toHaveBeenCalledWith(
      expect.objectContaining({ name: "新订阅" }),
    );
  });

  it("delete confirms then calls deleteSubscription", async () => {
    hoisted.listSubscriptions.mockResolvedValue([SAMPLE_SUB]);
    hoisted.fetchProjects.mockResolvedValue({ items: [], total: 0, page: 1, size: 200 });
    hoisted.deleteSubscription.mockResolvedValue(undefined);

    const wrapper = mount(SubscriptionView);
    await flushPromises();

    clickByText(wrapper, "删除").trigger("click");
    await flushPromises();

    expect(hoisted.deleteSubscription).toHaveBeenCalledWith(11);
  });

  it("non-superuser hides the view-all toggle", async () => {
    hoisted.authUser.is_superuser = false;
    hoisted.listSubscriptions.mockResolvedValue([]);
    hoisted.fetchProjects.mockResolvedValue({ items: [], total: 0, page: 1, size: 200 });

    const wrapper = mount(SubscriptionView);
    await flushPromises();

    expect(wrapper.text()).not.toContain("查看全部");
    hoisted.authUser.is_superuser = true;
  });
});
