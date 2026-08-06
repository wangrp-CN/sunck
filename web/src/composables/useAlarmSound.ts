import { onUnmounted, ref } from "vue";

/** 新告警声光提醒默认持续时长（毫秒） */
export const ALARM_SOUND_DURATION = 15000;

/**
 * 新告警声光提醒：用 Web Audio API 生成短促蜂鸣，无需外部音频文件。
 * - 每 900ms 蜂鸣一次，duration 后自动停止；
 * - 无 AudioContext（如 node 测试环境）时静默降级；
 * - 组件卸载自动停止。
 */
export function useAlarmSound(duration: number = ALARM_SOUND_DURATION) {
  const playing = ref(false);
  let timer: ReturnType<typeof setInterval> | null = null;
  let stopTimer: ReturnType<typeof setTimeout> | null = null;
  let ctx: AudioContext | null = null;

  function beep() {
    if (typeof window === "undefined") return;
    const AudioCtx =
      window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    if (!ctx) {
      try {
        ctx = new AudioCtx();
      } catch {
        return;
      }
    }
    if (ctx.state === "suspended") ctx.resume().catch(() => undefined);
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.value = 0.04;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    osc.stop(ctx.currentTime + 0.2);
  }

  function clearTimers() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    if (stopTimer) {
      clearTimeout(stopTimer);
      stopTimer = null;
    }
  }

  function start() {
    clearTimers();
    playing.value = true;
    beep();
    timer = setInterval(beep, 900);
    stopTimer = setTimeout(stop, duration);
  }

  function stop() {
    playing.value = false;
    clearTimers();
    if (ctx) {
      ctx.close().catch(() => undefined);
      ctx = null;
    }
  }

  onUnmounted(stop);

  return { playing, start, stop };
}
