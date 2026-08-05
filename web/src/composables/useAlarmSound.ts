// 报警声音提示组合式函数。
// 原型要求：每当系统收到一条新的报警，要有报警声音的提示，声音持续 15s。
// 采用 Web Audio API 合成「嘀—嘀」双频蜂鸣，避免引入额外音频资源文件；
// 浏览器自动播放策略下若未获得音频上下文授权，静默降级（不影响页面其它功能）。
import { onUnmounted, ref } from "vue";

/** 声音默认持续时长（毫秒），与原型注释一致 */
export const ALARM_SOUND_DURATION = 15000;
/** 单次蜂鸣间隔（毫秒） */
const BEEP_INTERVAL = 900;
/** 单次蜂鸣时长（秒） */
const BEEP_LENGTH = 0.28;

type AudioCtor = typeof AudioContext;

function getAudioCtor(): AudioCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    AudioContext?: AudioCtor;
    webkitAudioContext?: AudioCtor;
  };
  return w.AudioContext || w.webkitAudioContext || null;
}

/**
 * 报警声音控制。
 * - `playing` 是否正在响铃，可用于驱动「静音」按钮/闪烁样式
 * - `start()` 开始循环蜂鸣，到时自动停止；重复调用会重新计时
 * - `stop()` 立即停止并清理定时器
 * 组件卸载时自动停止，避免离开页面后仍在响。
 */
export function useAlarmSound(duration: number = ALARM_SOUND_DURATION) {
  const playing = ref(false);
  let ctx: AudioContext | null = null;
  let beepTimer: number | undefined;
  let stopTimer: number | undefined;

  function beep() {
    const Ctor = getAudioCtor();
    if (!Ctor) return;
    try {
      if (!ctx) ctx = new Ctor();
      // 部分浏览器初始为 suspended，需在用户交互后恢复
      if (ctx.state === "suspended") void ctx.resume();
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      // 双频交替，接近工业报警器音色
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.setValueAtTime(660, now + BEEP_LENGTH / 2);
      // 淡入淡出，避免爆音
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.25, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + BEEP_LENGTH);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + BEEP_LENGTH);
    } catch {
      // 音频不可用时静默降级
    }
  }

  function stop() {
    playing.value = false;
    if (beepTimer !== undefined) {
      window.clearInterval(beepTimer);
      beepTimer = undefined;
    }
    if (stopTimer !== undefined) {
      window.clearTimeout(stopTimer);
      stopTimer = undefined;
    }
  }

  function start() {
    // 重复触发时重新计时，保证「最新一条报警」也能响满设定时长
    stop();
    playing.value = true;
    beep();
    beepTimer = window.setInterval(beep, BEEP_INTERVAL);
    stopTimer = window.setTimeout(stop, duration);
  }

  onUnmounted(stop);

  return { playing, start, stop };
}
