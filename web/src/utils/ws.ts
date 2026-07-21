// 实时 WebSocket 客户端：连接 /ws/alarm，心跳保活 + 断线重连。
// 后端推送两种消息：{type:"location",data} 与 {type:"alarm",data}。
import { getToken } from "@/utils/request";
import type { LocationItem, AlarmItem } from "@/api/realtime";

export interface RealtimeHandlers {
  onLocation?: (loc: LocationItem) => void;
  onAlarm?: (alarm: AlarmItem) => void;
  onStatus?: (connected: boolean) => void;
}

function wsBase(): string {
  // 同源反代：直接复用页面协议(ws/wss)与 host（含端口），
  // 开发期经 vite /ws 代理、生产期经 nginx /ws 代理，均无需硬编码端口。
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host; // 含非标准端口（如开发期 :5173）
  return `${proto}//${host}/ws/alarm`;
}

export function createRealtimeSocket(
  projectId: number | null,
  handlers: RealtimeHandlers,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let heartbeat: number | undefined;
  let reconnectTimer: number | undefined;

  const connect = () => {
    const token = getToken();
    if (!token) {
      handlers.onStatus?.(false);
      return;
    }
    const url = `${wsBase()}?token=${encodeURIComponent(token)}` +
      (projectId ? `&project_id=${projectId}` : "");
    ws = new WebSocket(url);

    ws.onopen = () => {
      handlers.onStatus?.(true);
      // 心跳：每 25s 发一次 ping
      heartbeat = window.setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 25000);
    };

    ws.onmessage = (ev) => {
      const text = String(ev.data);
      if (text === "pong") return;
      try {
        const msg = JSON.parse(text) as { type: string; data: unknown };
        if (msg.type === "location") handlers.onLocation?.(msg.data as LocationItem);
        else if (msg.type === "alarm") handlers.onAlarm?.(msg.data as AlarmItem);
      } catch {
        /* 忽略非 JSON 消息 */
      }
    };

    ws.onclose = () => {
      if (heartbeat) window.clearInterval(heartbeat);
      handlers.onStatus?.(false);
      if (!closed) reconnectTimer = window.setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws?.close();
    };
  };

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    if (heartbeat) window.clearInterval(heartbeat);
    ws?.close();
  };
}
