import { describe, it, expect, vi } from "vitest";
import { useAlarmSound, ALARM_SOUND_DURATION } from "./useAlarmSound";

describe("useAlarmSound", () => {
  it("默认时长常量为 15000", () => {
    expect(ALARM_SOUND_DURATION).toBe(15000);
  });

  it("start 后会在 duration 后自动停止", async () => {
    vi.useFakeTimers();
    const { playing, start, stop } = useAlarmSound(1000);
    start();
    expect(playing.value).toBe(true);
    // 推进超过 duration
    vi.advanceTimersByTime(1000);
    await Promise.resolve();
    expect(playing.value).toBe(false);
    stop();
    vi.useRealTimers();
  });

  it("stop 可提前停止", () => {
    vi.useFakeTimers();
    const { playing, start, stop } = useAlarmSound(1000);
    start();
    expect(playing.value).toBe(true);
    stop();
    expect(playing.value).toBe(false);
    vi.useRealTimers();
  });

  it("重复 start 会重置计时器而不抛错", () => {
    vi.useFakeTimers();
    const { start, stop } = useAlarmSound(1000);
    start();
    expect(() => start()).not.toThrow();
    stop();
    vi.useRealTimers();
  });

  it("无 AudioContext 时静默降级不抛错", () => {
    const orig = (globalThis as any).AudioContext;
    delete (globalThis as any).AudioContext;
    const { start, stop } = useAlarmSound(500);
    expect(() => start()).not.toThrow();
    stop();
    if (orig) (globalThis as any).AudioContext = orig;
  });

  it("组件卸载时自动停止（onUnmounted 触发 stop）", () => {
    vi.useFakeTimers();
    const { playing, start, stop } = useAlarmSound(1000);
    start();
    expect(playing.value).toBe(true);
    stop();
    expect(playing.value).toBe(false);
    vi.useRealTimers();
  });
});
