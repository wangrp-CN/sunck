import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import ElementPlus from "element-plus";
import CommandView from "@/views/CommandView.vue";

const hoisted = vi.hoisted(() => ({
  listCommands: vi.fn(),
  retryCommand: vi.fn(),
}));

vi.mock("@/api/command", () => ({
  listCommands: hoisted.listCommands,
  retryCommand: hoisted.retryCommand,
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ElMessage: {
      success: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
      info: vi.fn(),
    },
  };
});

const sampleRows = [
  {
    id: 1,
    device_no: "D-001",
    device_type: "locate",
    action: "alarm",
    status: "sent",
    retry_count: 0,
    params_json: { on: false },
    alarm_id: null,
    sent_at: "2026-07-28 16:40:00",
    acked_at: null,
  },
  {
    id: 2,
    device_no: "D-002",
    device_type: "anti_intrusion",
    action: "capture",
    status: "acked",
    retry_count: 0,
    params_json: null,
    alarm_id: 9,
    sent_at: "2026-07-28 16:30:00",
    acked_at: "2026-07-28 16:30:05",
  },
];

beforeEach(() => {
  hoisted.listCommands.mockReset();
  hoisted.retryCommand.mockReset();
  hoisted.listCommands.mockResolvedValue({
    items: sampleRows,
    total: sampleRows.length,
    page: 1,
    size: 20,
  });
  hoisted.retryCommand.mockResolvedValue({ id: 1, status: "sent" });
});

describe("CommandView", () => {
  it("挂载即加载指令列表", async () => {
    const wrapper = mount(CommandView, { global: { plugins: [ElementPlus] } });
    await new Promise((r) => setTimeout(r, 0));
    expect(hoisted.listCommands).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("指令下发记录");
    expect(wrapper.text()).toContain("D-001");
  });

  it("按设备类型筛选会带参重新查询", async () => {
    const wrapper = mount(CommandView, { global: { plugins: [ElementPlus] } });
    await new Promise((r) => setTimeout(r, 0));
    hoisted.listCommands.mockClear();
    // 选择设备类型并点击查询
    const selects = wrapper.findAllComponents({ name: "ElSelect" });
    await selects[0].setValue("locate");
    await wrapper.findAll("button").find((b) => b.text() === "查询")?.trigger("click");
    await new Promise((r) => setTimeout(r, 0));
    expect(hoisted.listCommands).toHaveBeenCalledWith(
      expect.objectContaining({ device_type: "locate" }),
    );
  });

  it("已回执行不显示重试按钮，未回执可重试", async () => {
    const wrapper = mount(CommandView, { global: { plugins: [ElementPlus] } });
    await new Promise((r) => setTimeout(r, 0));
    // 第一行 status=sent 有重试；第二行 status=acked 无重试
    const retryButtons = wrapper.findAll("button").filter((b) => b.text() === "重试");
    expect(retryButtons.length).toBe(1);
    await retryButtons[0].trigger("click");
    await new Promise((r) => setTimeout(r, 0));
    expect(hoisted.retryCommand).toHaveBeenCalledWith(1);
  });
});
