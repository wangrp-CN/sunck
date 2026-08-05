// useAlarmSound 单测：报警声音在指定时长后自动停止，可手动停止，卸载时清理。
import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";
import { ALARM_SOUND_DURATION, useAlarmSound } from "@/composables/useAlarmSound";

function harness(duration?: number) {
  let api: ReturnType<typeof useAlarmSound> | null = null;
  const Comp = defineComponent({
    setup() {
      api = useAlarmSound(duration);
      return () => null;
    },
  });
  const wrapper = mount(Comp);
  return { wrapper, api: api! };
}

describe("useAlarmSound", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("默认持续时长为 15 秒（与原型一致）", () => {
    expect(ALARM_SOUND_DURATION).toBe(15000);
  });

  it("start 后 playing 为真，到时自动停止", () => {
    const { api } = harness(15000);
    expect(api.playing.value).toBe(false);

    api.start();
    expect(api.playing.value).toBe(true);

    vi.advanceTimersByTime(14000);
    expect(api.playing.value).toBe(true);

    vi.advanceTimersByTime(1500);
    expect(api.playing.value).toBe(false);
  });

  it("stop 可提前静音", () => {
    const { api } = harness(15000);
    api.start();
    expect(api.playing.value).toBe(true);
    api.stop();
    expect(api.playing.value).toBe(false);
  });

  it("重复 start 会重新计时", () => {
    const { api } = harness(15000);
    api.start();
    vi.advanceTimersByTime(10000);
    // 新告警到达，重新计时
    api.start();
    vi.advanceTimersByTime(10000);
    expect(api.playing.value).toBe(true);
    vi.advanceTimersByTime(6000);
    expect(api.playing.value).toBe(false);
  });

  it("组件卸载后停止响铃", () => {
    const { wrapper, api } = harness(15000);
    api.start();
    expect(api.playing.value).toBe(true);
    wrapper.unmount();
    expect(api.playing.value).toBe(false);
  });

  it("环境无 AudioContext 时静默降级，不抛异常", () => {
    const original = (window as unknown as { AudioContext?: unknown }).AudioContext;
    // jsdom 默认无 AudioContext，显式删除以覆盖降级分支
    delete (window as unknown as { AudioContext?: unknown }).AudioContext;
    const { api } = harness(1000);
    expect(() => api.start()).not.toThrow();
    api.stop();
    if (original) {
      (window as unknown as { AudioContext?: unknown }).AudioContext = original;
    }
  });
});
