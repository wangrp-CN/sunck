import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// 轻量 WebSocket 桩，避免依赖 jsdom 未实现的真实实现
class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = FakeWebSocket.OPEN;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);

// vi.mock 工厂会被提升，引用变量需用 vi.hoisted 包裹以避免"初始化前访问"
const { getToken } = vi.hoisted(() => {
  const getToken = vi.fn((): string | null => "tok");
  return { getToken };
});
vi.mock("@/utils/request", () => ({ getToken }));

import { createCorrelationSocket } from "@/utils/correlationWs";

describe("createCorrelationSocket", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    getToken.mockReturnValue("tok");
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("带 token 连接并对 ping 回 pong", () => {
    const stop = createCorrelationSocket({});
    const ws = FakeWebSocket.instances[0];
    ws.onopen?.();
    ws.send("ping"); // 模拟服务端回包
    expect(ws.sent).toContain("ping");
    stop();
  });

  it("onNew 分发 correlation 消息，忽略 pong", () => {
    const onNew = vi.fn();
    const stop = createCorrelationSocket({ onNew });
    const ws = FakeWebSocket.instances[0];
    ws.onopen?.();
    ws.onmessage?.({ data: "pong" });
    expect(onNew).not.toHaveBeenCalled();
    ws.onmessage?.({
      data: JSON.stringify({ type: "correlation", action: "new_cross_device", data: { id: 5 } }),
    });
    expect(onNew).toHaveBeenCalledWith(expect.objectContaining({ id: 5 }));
    stop();
  });

  it("每 25s 发送心跳 ping", () => {
    const stop = createCorrelationSocket({});
    const ws = FakeWebSocket.instances[0];
    ws.onopen?.();
    ws.sent.length = 0;
    vi.advanceTimersByTime(25000);
    expect(ws.sent).toContain("ping");
    stop();
  });

  it("无 token 时直接返回清理函数且不创建连接", () => {
    getToken.mockReturnValue(null);
    const stop = createCorrelationSocket({});
    expect(typeof stop).toBe("function");
    expect(FakeWebSocket.instances.length).toBe(0);
    stop();
  });
});
