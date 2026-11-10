import type { Rng } from './rng';

/** 座位号，从 0 开始，按逆时针（出牌顺序）排列。 */
export type Seat = number;

/** 系统动作使用的虚拟座位（例如定时自动推进）。 */
export const SYSTEM_SEAT: Seat = -1;

export interface PlayerSlot {
  name: string;
  isBot: boolean;
}

/** 游戏设置项的描述，前端会据此自动生成设置表单。 */
export type OptionField =
  | {
      key: string;
      label: string;
      hint?: string;
      type: 'select';
      choices: { value: string | number; label: string }[];
    }
  | {
      key: string;
      label: string;
      hint?: string;
      type: 'toggle';
    };

/** 玩法大类：大厅据此分组展示 */
export type GameCategory = 'poker' | 'mahjong' | 'chess' | 'board' | 'casual';

export interface GameMeta {
  id: string;
  category: GameCategory;
  name: string;
  nameEn: string;
  /** 一句话简介 */
  tagline: string;
  minPlayers: number;
  maxPlayers: number;
  defaultPlayers: number;
  /** 规则要点（展示在规则面板） */
  rules: string[];
  /** 是否为示例 / 实验玩法 */
  experimental?: boolean;
  /** 电脑出牌的思考时间范围（毫秒） */
  botDelayMs?: [number, number];
  /** 联机时真人每步的时限（毫秒），超时由电脑代为行动；不填则用服务器的默认值。棋类需要更长 */
  turnTimeoutMs?: number;
}

export interface SetupContext<O> {
  players: PlayerSlot[];
  options: O;
  seed: number;
}

/**
 * 一个玩法（插件）需要实现的全部接口。
 *
 * 约定：
 * - State 必须是可 JSON 序列化的纯数据；
 * - apply 不得修改传入的 state，而是返回新对象；
 * - view 返回某个座位"能看到的信息"，联机时只会把 view 发给客户端，避免作弊；
 * - bot 只能基于 view 做决策，因此单机和联机的电脑玩家行为一致。
 */
export interface GameDefinition<S = any, A = any, V = any, O = any> {
  meta: GameMeta;
  defaultOptions: O;
  optionFields: OptionField[];

  setup(ctx: SetupContext<O>): S;
  /** 当前需要行动的座位（可以同时有多个，例如"准备下一局"）。 */
  activeSeats(state: S): Seat[];
  /** 校验动作，合法返回 null，否则返回给玩家看的错误提示。 */
  validate(state: S, seat: Seat, action: A): string | null;
  apply(state: S, seat: Seat, action: A): S;
  view(state: S, seat: Seat | null): V;
  isOver(state: S): boolean;
  bot(view: V, seat: Seat, rng: Rng): A;
  /** 可选：需要系统定时推进时返回动作与延迟。 */
  autoAdvance?(state: S): { delayMs: number; action: A } | null;
  /**
   * 可选：把某个座位的 view 整理成给大模型看的局面与候选动作。
   * 返回 null 表示这一步不需要大模型（例如"准备"），由规则电脑处理。
   */
  aiPrompt?(view: V, seat: Seat, rng: Rng): AiPrompt<A> | null;
}

/** 交给大模型的一个候选动作 */
export interface AiOption<A = unknown> {
  label: string;
  action: A;
}

/** 交给大模型的局面：文字描述 + 候选动作（第 1 个是规则电脑的推荐） */
export interface AiPrompt<A = unknown> {
  situation: string;
  options: AiOption<A>[];
}

export type AnyGame = GameDefinition<any, any, any, any>;
