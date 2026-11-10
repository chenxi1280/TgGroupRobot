import { Rng, randomSeed } from './rng';
import type { TimerHandle } from './timers';
import { clearTimer, setTimer } from './timers';
import type { AnyGame, Seat } from './types';
import { SYSTEM_SEAT } from './types';

export interface TableSeat {
  name: string;
  isBot: boolean;
  /** 形象 id（界面用的元数据，规则不关心） */
  avatar?: string;
  /** 托管：由电脑代打 */
  auto?: boolean;
  /** 联机时玩家是否在线，离线视同托管 */
  connected?: boolean;
  /** 由外部（例如大模型）接管决策的电脑玩家 */
  ai?: boolean;
}

export interface TableConfig {
  /** 真人玩家的操作时限，超时由电脑代打一步；null 表示不限时（单机） */
  humanTimeoutMs?: number | null;
  /** 托管 / 离线玩家的代打延迟 */
  autoDelayMs?: number;
  /** 便于测试：关闭所有定时器，由调用方手动推进 */
  manual?: boolean;
  seed?: number;
  /** 从已保存的状态恢复（例如刷新页面后继续单机对局） */
  initialState?: unknown;
  onError?: (err: unknown) => void;
  /**
   * 可选：电脑座位轮到行动时，交给外部异步决策（例如大模型）。
   * 返回 Promise 表示接管这一步；返回 null 则照常由规则电脑决策。
   * 结果过期（期间局面已变化）会被丢弃；出错或动作不合法时退回规则电脑。
   */
  delegate?: (seat: Seat, ctx: DelegateContext) => Promise<unknown> | null;
}

/** 外部决策的上下文：被取消（例如关闭 AI 接管）时会调用 onCancel 注册的回调 */
export interface DelegateContext {
  onCancel(fn: () => void): void;
}

export interface LastAction {
  seat: Seat;
  action: unknown;
  at: number;
}

type Listener = () => void;

/**
 * 牌桌运行器：持有一局游戏的状态，负责校验/应用动作、调度电脑玩家与超时。
 * 单机（浏览器内）与联机（服务器端）共用同一份实现。
 */
export class Table<G extends AnyGame = AnyGame> {
  state: ReturnType<G['setup']>;
  version = 0;
  lastAction: LastAction | null = null;
  /** 各座位本次行动的截止时间戳（毫秒），用于前端显示倒计时 */
  deadlines: Record<number, number> = {};

  private listeners = new Set<Listener>();
  private seatTimers = new Map<Seat, TimerHandle>();
  private systemTimer: TimerHandle | null = null;
  private disposed = false;
  private running = false;
  private thinkingSeats = new Set<Seat>();
  /** 思考期间曾经不再需要行动的座位：结果作废 */
  private thinkingStale = new Set<Seat>();
  /** 每次外部决策的编号与取消回调：结果编号不匹配即作废 */
  private thinkingToken = new Map<Seat, number>();
  private thinkingCancel = new Map<Seat, () => void>();
  private tokenSeq = 0;

  constructor(
    public readonly def: G,
    public readonly seats: TableSeat[],
    public readonly options: Parameters<G['setup']>[0]['options'],
    private readonly config: TableConfig = {},
  ) {
    const seed = config.seed ?? randomSeed();
    this.state =
      (config.initialState as ReturnType<G['setup']>) ??
      def.setup({
        players: seats.map((s) => ({ name: s.name, isBot: s.isBot })),
        options,
        seed,
      });
  }

  /** 开始调度（电脑玩家开始行动）。可在 stop() 之后再次调用。 */
  start(): void {
    if (this.disposed) return;
    this.running = true;
    this.schedule(null);
  }

  /** 暂停调度：清除所有定时器，状态保留。 */
  stop(): void {
    this.running = false;
    this.clearAllTimers();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  view(seat: Seat | null): ReturnType<G['view']> {
    return this.def.view(this.state, seat);
  }

  isOver(): boolean {
    return this.def.isOver(this.state);
  }

  activeSeats(): Seat[] {
    return this.def.activeSeats(this.state);
  }

  /** 正在等待外部决策（思考中）的座位 */
  get thinking(): Seat[] {
    return [...this.thinkingSeats];
  }

  /** 执行一个动作，成功返回 null，失败返回错误提示。 */
  act(seat: Seat, action: unknown): string | null {
    if (this.disposed) return '牌桌已关闭';
    if (this.def.isOver(this.state)) return '本场已结束';
    if (seat !== SYSTEM_SEAT && !this.def.activeSeats(this.state).includes(seat)) {
      return '还没轮到你';
    }
    // 所有玩法的动作都是带字符串 type 的普通对象：其余直接拒绝（联机时来自不可信客户端）
    if (!action || typeof action !== 'object' || Array.isArray(action)) return '无效操作';
    if (typeof (action as { type?: unknown }).type !== 'string') return '无效操作';
    let err: string | null;
    try {
      err = this.def.validate(this.state, seat, action);
    } catch (e) {
      this.config.onError?.(e);
      return '无效操作';
    }
    if (err) return err;
    this.state = this.def.apply(this.state, seat, action);
    this.version++;
    if (this.thinkingSeats.size) {
      const stillActive = new Set(this.def.activeSeats(this.state));
      for (const s of this.thinkingSeats) if (!stillActive.has(s)) this.thinkingStale.add(s);
    }
    this.lastAction = { seat, action, at: Date.now() };
    this.schedule(seat);
    this.emit();
    return null;
  }

  /** 让电脑替某个座位走一步（托管 / 超时 / 提示）。 */
  botAction(seat: Seat): unknown {
    const view = this.def.view(this.state, seat);
    return this.def.bot(view, seat, new Rng(randomSeed()));
  }

  setAuto(seat: Seat, auto: boolean): void {
    const s = this.seats[seat];
    if (!s || !!s.auto === auto) return;
    s.auto = auto;
    this.clearSeatTimer(seat);
    this.schedule(null);
    this.emit();
  }

  /**
   * 开关某个电脑座位的外部决策（AI 接管）。
   * 关闭时若正在等待外部结果，立即取消；轮到它行动的话由规则电脑马上出手，不再等待。
   */
  setAi(seat: Seat, on: boolean): void {
    const s = this.seats[seat];
    if (!s || !!s.ai === on) return;
    s.ai = on;
    this.clearSeatTimer(seat);
    if (!on) {
      this.cancelThinking(seat);
      const due =
        this.running &&
        !this.disposed &&
        s.isBot &&
        !this.def.isOver(this.state) &&
        this.def.activeSeats(this.state).includes(seat);
      if (due) {
        const before = this.version;
        this.runRuleBot(seat);
        if (this.version !== before) return;
      }
    }
    this.schedule(null);
    this.emit();
  }

  private cancelThinking(seat: Seat): void {
    if (!this.thinkingSeats.delete(seat)) return;
    this.thinkingToken.delete(seat);
    this.thinkingStale.delete(seat);
    const cancel = this.thinkingCancel.get(seat);
    this.thinkingCancel.delete(seat);
    try {
      cancel?.();
    } catch (e) {
      this.config.onError?.(e);
    }
  }

  setConnected(seat: Seat, connected: boolean): void {
    const s = this.seats[seat];
    if (!s || s.connected === connected) return;
    s.connected = connected;
    this.clearSeatTimer(seat);
    this.schedule(null);
    this.emit();
  }

  setSeat(seat: Seat, patch: Partial<TableSeat>): void {
    const s = this.seats[seat];
    if (!s) return;
    Object.assign(s, patch);
    this.clearSeatTimer(seat);
    this.schedule(null);
    this.emit();
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
    this.listeners.clear();
  }

  private clearAllTimers(): void {
    for (const t of this.seatTimers.values()) clearTimer(t);
    this.seatTimers.clear();
    this.deadlines = {};
    if (this.systemTimer) clearTimer(this.systemTimer);
    this.systemTimer = null;
  }

  // ---------------------------------------------------------------------------

  private emit(): void {
    for (const fn of [...this.listeners]) {
      try {
        fn();
      } catch (e) {
        this.config.onError?.(e);
      }
    }
  }

  private isAutomated(seat: Seat): boolean {
    const s = this.seats[seat];
    return !s || s.isBot || !!s.auto || s.connected === false;
  }

  private clearSeatTimer(seat: Seat): void {
    const t = this.seatTimers.get(seat);
    if (t) clearTimer(t);
    this.seatTimers.delete(seat);
    delete this.deadlines[seat];
  }

  /**
   * 重新调度定时器。actedSeat 是刚刚行动的座位，它的计时需要重置；
   * 其他仍处于行动中的座位保留原计时（例如多人同时"准备"的阶段）。
   */
  private schedule(actedSeat: Seat | null): void {
    if (this.config.manual || this.disposed || !this.running) return;
    if (actedSeat !== null) this.clearSeatTimer(actedSeat);
    if (this.systemTimer) clearTimer(this.systemTimer);
    this.systemTimer = null;

    if (this.def.isOver(this.state)) {
      for (const seat of [...this.seatTimers.keys()]) this.clearSeatTimer(seat);
      return;
    }

    const active = new Set(this.def.activeSeats(this.state));
    for (const seat of [...this.seatTimers.keys()]) {
      if (!active.has(seat)) this.clearSeatTimer(seat);
    }

    const auto = this.def.autoAdvance?.(this.state);
    if (auto) {
      const version = this.version;
      this.systemTimer = setTimer(() => {
        if (this.version === version) this.act(SYSTEM_SEAT, auto.action);
      }, auto.delayMs);
    }

    for (const seat of active) {
      if (this.seatTimers.has(seat) || this.thinkingSeats.has(seat)) continue;
      let delay: number | null = null;
      if (this.isAutomated(seat)) {
        const s = this.seats[seat];
        if (s?.isBot) {
          const [lo, hi] = this.def.meta.botDelayMs ?? [600, 1200];
          delay = lo + Math.random() * (hi - lo);
        } else {
          delay = this.config.autoDelayMs ?? 700;
        }
      } else if (this.config.humanTimeoutMs) {
        delay = this.config.humanTimeoutMs;
        this.deadlines[seat] = Date.now() + delay;
      }
      if (delay === null) continue;
      const timer = setTimer(() => {
        this.seatTimers.delete(seat);
        delete this.deadlines[seat];
        this.runBot(seat);
      }, delay);
      this.seatTimers.set(seat, timer);
    }
  }

  private runBot(seat: Seat): void {
    if (this.disposed || this.def.isOver(this.state)) return;
    if (!this.def.activeSeats(this.state).includes(seat)) return;
    let pending: Promise<unknown> | null = null;
    const token = ++this.tokenSeq;
    this.thinkingToken.set(seat, token);
    try {
      pending = this.seats[seat]?.isBot
        ? (this.config.delegate?.(seat, {
            onCancel: (fn) => {
              if (this.thinkingToken.get(seat) === token) this.thinkingCancel.set(seat, fn);
            },
          }) ?? null)
        : null;
    } catch (e) {
      this.config.onError?.(e);
    }
    if (!pending) {
      this.thinkingToken.delete(seat);
      this.thinkingCancel.delete(seat);
    }
    if (pending) {
      this.thinkingSeats.add(seat);
      this.thinkingStale.delete(seat);
      this.emit();
      pending.then(
        (action) => this.finishDelegate(seat, token, action, null),
        (err) => this.finishDelegate(seat, token, undefined, err ?? new Error('delegate failed')),
      );
      return;
    }
    this.runRuleBot(seat);
  }

  private finishDelegate(seat: Seat, token: number, action: unknown, err: unknown): void {
    // 已被取消（例如关闭了 AI 接管）：结果作废
    if (this.thinkingToken.get(seat) !== token) return;
    this.thinkingToken.delete(seat);
    this.thinkingCancel.delete(seat);
    this.thinkingSeats.delete(seat);
    const brokeOff = this.thinkingStale.delete(seat);
    if (this.disposed) return;
    // 其他座位在此期间行动（例如同时出牌）不影响；只有这个座位中途不再需要行动才算过期
    const stale =
      brokeOff ||
      !this.running ||
      this.def.isOver(this.state) ||
      !this.def.activeSeats(this.state).includes(seat);
    if (stale) {
      // 局面已经变了：重新排队，下一次再决策
      this.schedule(null);
      this.emit();
      return;
    }
    if (err) this.config.onError?.(err);
    const rejected = err || action == null ? 'no action' : this.act(seat, action);
    if (rejected) {
      if (!err)
        this.config.onError?.(new Error(`delegate action rejected (seat ${seat}): ${rejected}`));
      const before = this.version;
      this.runRuleBot(seat);
      if (this.version === before) this.emit();
    }
  }

  private runRuleBot(seat: Seat): void {
    try {
      const action = this.botAction(seat);
      const err = this.act(seat, action);
      if (err) this.config.onError?.(new Error(`bot action rejected (seat ${seat}): ${err}`));
    } catch (e) {
      this.config.onError?.(e);
    }
  }
}

/**
 * 不依赖定时器、同步跑完整局的辅助函数（用于测试与模拟）。
 * 所有座位均由 bot 决策，返回最终状态与步数。
 */
export function simulate<G extends AnyGame>(
  def: G,
  numPlayers: number,
  options: Parameters<G['setup']>[0]['options'],
  seed: number,
  maxSteps = 20000,
): { state: ReturnType<G['setup']>; steps: number } {
  const rng = new Rng(seed);
  let state = def.setup({
    players: Array.from({ length: numPlayers }, (_, i) => ({ name: `P${i + 1}`, isBot: true })),
    options,
    seed,
  });
  let steps = 0;
  while (!def.isOver(state) && steps < maxSteps) {
    const active = def.activeSeats(state);
    if (active.length === 0) {
      const auto = def.autoAdvance?.(state);
      if (!auto) throw new Error('no active seats and no auto-advance');
      state = def.apply(state, SYSTEM_SEAT, auto.action);
      steps++;
      continue;
    }
    const seat = active[rng.int(active.length)];
    const action = def.bot(def.view(state, seat), seat, rng);
    const err = def.validate(state, seat, action);
    if (err) {
      throw new Error(
        `bot produced invalid action at step ${steps}: ${err} ${JSON.stringify(action)}`,
      );
    }
    state = def.apply(state, seat, action);
    steps++;
  }
  return { state, steps };
}
