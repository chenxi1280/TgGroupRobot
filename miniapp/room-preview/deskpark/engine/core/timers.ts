/**
 * 平台无关的定时器访问：引擎不依赖 DOM 或 Node 的类型声明，
 * 只要求运行环境提供标准的 setTimeout / clearTimeout。
 */
export type TimerHandle = unknown;

interface TimerHost {
  setTimeout(fn: () => void, ms: number): TimerHandle;
  clearTimeout(handle: TimerHandle): void;
}

const host = globalThis as unknown as TimerHost;

export const setTimer = (fn: () => void, ms: number): TimerHandle => host.setTimeout(fn, ms);
export const clearTimer = (handle: TimerHandle): void => host.clearTimeout(handle);
