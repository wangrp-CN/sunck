// DeviceHealthView 单测（设备健康：分页拉取 / 序号列 / 切换每页条数即刷新）
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DeviceHealthView from "@/views/DeviceHealthView.vue";

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: { permission_codes: ["device:list"] },
    hasPermission: () => true,
    loadProfile: vi.fn(),
  })),
}));

vi.mock("@/api/device", () => ({ fetchDeviceHealth: vi.fn() }));
vi.mock("@/api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("@/api/metrics", () => ({ getHealthTrend: vi.fn() }));
vi.mock("@/api/realtime", () => ({
  DEVICE_TYPE_LABELS: { locate: "人机定位", anti_intrusion: "大机防侵限" },
}));

import { fetchDeviceHealth } from "@/api/device";
import { fetchProjects } from "@/api/project";

function healthResp(page = 1, size = 20) {
  return {
    window_hours: 24,
    threshold_seconds: 300,
    total: 135,
    online: 100,
    offline: 35,
    page,
    size,
    items: [
      {
        device_no: "LOC-1",
        name: "定位1",
        type_label: "人机定位",
        project_id: 1,
        online: true,
        online_state: "fresh",
        last_report_time: "2026-08-04 09:00:00",
        report_count: 12,
        alarm_count: 0,
        health_score: 100,
        health_level: "优",
      },
      {
        device_no: "LOC-2",
        name: "定位2",
        type_label: "人机定位",
        project_id: 1,
        online: false,
        online_state: "offline",
        last_report_time: null,
        report_count: 0,
        alarm_count: 3,
        health_score: 20,
        health_level: "差",
      },
    ],
  };
}

let wrapper: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchDeviceHealth).mockResolvedValue(healthResp() as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: 1, name: "项目A" }],
    total: 1,
  } as any);
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("views/DeviceHealthView.vue", () => {
  it("挂载后按分页参数拉取，并回填总数", async () => {
    wrapper = mount(DeviceHealthView);
    await flushPromises();

    expect(vi.mocked(fetchDeviceHealth)).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, size: 20 }),
    );
    const vm = wrapper.vm as any;
    expect(vm.total).toBe(135);
    expect(wrapper.text()).toContain("定位1");
  });

  it("渲染分页组件与序号列", async () => {
    wrapper = mount(DeviceHealthView);
    await flushPromises();

    const pager = wrapper.findComponent({ name: "TablePager" });
    expect(pager.exists()).toBe(true);
    expect(pager.props("total")).toBe(135);
    expect(wrapper.text()).toContain("序号");
  });

  it("切换每页条数：重置到第 1 页并按新条数立即重新拉取", async () => {
    wrapper = mount(DeviceHealthView);
    await flushPromises();

    const vm = wrapper.vm as any;
    vm.page = 3;
    await flushPromises();
    vi.mocked(fetchDeviceHealth).mockClear();

    const pagination = wrapper.findComponent({ name: "ElPagination" });
    await pagination.vm.$emit("size-change", 50);
    await flushPromises();

    expect(vm.size).toBe(50);
    expect(vm.page).toBe(1);
    expect(vi.mocked(fetchDeviceHealth)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchDeviceHealth)).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, size: 50 }),
    );
  });

  it("翻页按新页码重新拉取", async () => {
    wrapper = mount(DeviceHealthView);
    await flushPromises();
    vi.mocked(fetchDeviceHealth).mockClear();

    const pagination = wrapper.findComponent({ name: "ElPagination" });
    await pagination.vm.$emit("current-change", 2);
    await flushPromises();

    expect(vi.mocked(fetchDeviceHealth)).toHaveBeenCalledWith(
      expect.objectContaining({ page: 2, size: 20 }),
    );
  });

  it("条件查询回到第 1 页", async () => {
    wrapper = mount(DeviceHealthView);
    await flushPromises();

    const vm = wrapper.vm as any;
    vm.page = 4;
    await flushPromises();
    vi.mocked(fetchDeviceHealth).mockClear();

    vm.search();
    await flushPromises();

    expect(vm.page).toBe(1);
    expect(vi.mocked(fetchDeviceHealth)).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1 }),
    );
  });
});
