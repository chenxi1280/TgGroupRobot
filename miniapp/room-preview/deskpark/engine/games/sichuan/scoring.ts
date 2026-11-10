import type { StdDecomp } from '../../mahjong/analysis';
import { isSevenPairs, standardDecomps } from '../../mahjong/analysis';
import { KINDS, kindRank } from '../../mahjong/tiles';

/**
 * 四川麻将（成都血战到底，规则版本 chengdu-xz-1）番型与计分。
 *
 * - 牌型番取最高，不叠加；并列最高的牌型都列出，但只收一次番。
 * - 根：和牌后（暗手 + 副露）每有一组四张相同 +1；只有龙七对独占最高档时吞掉第一组根。
 * - 无副露时标准型与七对两种骨架都算，fan_raw（牌型 + 根 + 金钩钓）大者胜，相等七对优先。
 * - 自摸不加番。分 = 底分 × 2^(min(番, 5) − 1)。
 */

export type FanId =
  | 'pinghu'
  | 'duidui'
  | 'qingyise'
  | 'anqidui'
  | 'quanyaojiu'
  | 'qingyaojiu'
  | 'qingdui'
  | 'jiangdui'
  | 'qingqidui'
  | 'longqidui'
  | 'gen'
  | 'jingoudiao'
  | 'gangshanghua'
  | 'gangshangpao'
  | 'qianggang'
  | 'haidi'
  | 'tianhu'
  | 'dihu';

export const FAN_NAME: Record<FanId, string> = {
  pinghu: '平胡',
  duidui: '对对胡',
  qingyise: '清一色',
  anqidui: '暗七对',
  quanyaojiu: '全幺九',
  qingyaojiu: '清幺九',
  qingdui: '清对',
  jiangdui: '将对',
  qingqidui: '清七对',
  longqidui: '龙七对',
  gen: '根',
  jingoudiao: '金钩钓',
  gangshanghua: '杠上花',
  gangshangpao: '杠上炮',
  qianggang: '抢杠',
  haidi: '海底捞月',
  tianhu: '天胡',
  dihu: '地胡',
};

export const FAN_CAP = 5;

export interface MeldShape {
  type: 'pung' | 'kong';
  kind: number;
}

export interface HandValue {
  skeleton: 'standard' | 'qidui';
  /** 计分牌型（并列最高时可能有多个） */
  patterns: FanId[];
  patternFan: number;
  /** 有效根数（已扣除被龙七对吞掉的一组） */
  roots: number;
  jingoudiao: boolean;
  /** 牌型 + 根 + 金钩钓（不含过程番） */
  base: number;
}

export interface WinContext {
  selfDrawn: boolean;
  afterKong: boolean;
  robbing: boolean;
  haidi: boolean;
  tianhu: boolean;
  dihu: boolean;
}

export interface FanItem {
  id: FanId;
  fan: number;
}

export interface WinScore {
  skeleton: 'standard' | 'qidui';
  items: FanItem[];
  fanRaw: number;
  fanCharged: number;
  points: number;
}

export function scoreOf(fan: number, baseScore: number, cap = FAN_CAP): number {
  const f = Math.max(1, Math.min(fan, cap));
  return baseScore * 2 ** (f - 1);
}

const isTerminal = (kind: number) => kindRank(kind) === 1 || kindRank(kind) === 9;
const is258 = (kind: number) => [2, 5, 8].includes(kindRank(kind));

function combinedCounts(concealed: readonly number[], melds: readonly MeldShape[]): number[] {
  const c = [...concealed];
  for (const m of melds) c[m.kind] += m.type === 'kong' ? 4 : 3;
  return c;
}

function standardValue(
  d: StdDecomp,
  melds: readonly MeldShape[],
  qingyise: boolean,
  roots: number,
  jingoudiaoOn: boolean,
  concealedTotal: number,
): HandValue {
  const sets = [...d.sets, ...melds.map((m) => ({ type: 'pung' as const, kind: m.kind }))];
  const duidui = sets.every((s) => s.type === 'pung');
  const yaojiu =
    isTerminal(d.pair) &&
    sets.every((s) =>
      s.type === 'pung' ? isTerminal(s.kind) : kindRank(s.kind) === 1 || kindRank(s.kind) === 7,
    );
  const jiang = duidui && is258(d.pair) && sets.every((s) => is258(s.kind));
  const matched: [FanId, number][] = [['pinghu', 1]];
  if (duidui) matched.push(['duidui', 2]);
  if (qingyise) matched.push(['qingyise', 3]);
  if (yaojiu) matched.push(['quanyaojiu', 3]);
  if (qingyise && yaojiu) matched.push(['qingyaojiu', 4]);
  if (qingyise && duidui) matched.push(['qingdui', 4]);
  if (jiang) matched.push(['jiangdui', 4]);
  const top = Math.max(...matched.map((m) => m[1]));
  const jingoudiao = jingoudiaoOn && concealedTotal === 2;
  return {
    skeleton: 'standard',
    patterns: matched.filter((m) => m[1] === top).map((m) => m[0]),
    patternFan: top,
    roots,
    jingoudiao,
    base: top + roots + (jingoudiao ? 1 : 0),
  };
}

/**
 * 评估一手和牌（暗手计数已包含和进的那张）。不能和牌（形状不成立或花色超过两门）时返回 null。
 */
export function evaluateHand(
  concealed: readonly number[],
  melds: readonly MeldShape[],
  opts: { jingoudiao: boolean } = { jingoudiao: false },
): HandValue | null {
  const all = combinedCounts(concealed, melds);
  const suits = [0, 1, 2].filter((s) => all.slice(s * 9, s * 9 + 9).some((n) => n > 0));
  if (suits.length > 2) return null;
  const qingyise = suits.length === 1;
  let rootCount = 0;
  for (let k = 0; k < KINDS; k++) if (all[k] === 4) rootCount++;
  const concealedTotal = concealed.reduce((a, b) => a + b, 0);

  let best: HandValue | null = null;
  for (const d of standardDecomps(concealed, 4 - melds.length)) {
    const v = standardValue(d, melds, qingyise, rootCount, opts.jingoudiao, concealedTotal);
    if (!best || v.base > best.base) best = v;
  }

  if (isSevenPairs(concealed, melds.length)) {
    const has4 = concealed.some((n) => n === 4);
    const matched: [FanId, number][] = [];
    if (!has4) matched.push(['anqidui', 3]);
    if (has4) matched.push(['longqidui', 4]);
    if (qingyise) matched.push(['qingqidui', 4]);
    const top = Math.max(...matched.map((m) => m[1]));
    let charged = matched.filter((m) => m[1] === top).map((m) => m[0]);
    let absorb = charged.length === 1 && charged[0] === 'longqidui';
    if (charged.includes('longqidui') && charged.length > 1) {
      charged = charged.filter((p) => p !== 'longqidui');
      absorb = false;
    }
    const roots = Math.max(0, rootCount - (absorb ? 1 : 0));
    const v: HandValue = {
      skeleton: 'qidui',
      patterns: charged,
      patternFan: top,
      roots,
      jingoudiao: false,
      base: top + roots,
    };
    if (!best || v.base >= best.base) best = v;
  }
  return best;
}

/** 加上过程番，得到最终番数与分数 */
export function scoreWin(value: HandValue, ctx: WinContext, baseScore: number): WinScore {
  const items: FanItem[] = value.patterns.map((id, i) => ({
    id,
    fan: i === 0 ? value.patternFan : 0,
  }));
  if (value.roots > 0) items.push({ id: 'gen', fan: value.roots });
  if (value.jingoudiao) items.push({ id: 'jingoudiao', fan: 1 });
  if (ctx.afterKong && ctx.selfDrawn) items.push({ id: 'gangshanghua', fan: 1 });
  if (ctx.afterKong && !ctx.selfDrawn && !ctx.robbing) items.push({ id: 'gangshangpao', fan: 1 });
  if (ctx.robbing) items.push({ id: 'qianggang', fan: 1 });
  if (ctx.haidi && ctx.selfDrawn) items.push({ id: 'haidi', fan: 1 });
  if (ctx.tianhu) items.push({ id: 'tianhu', fan: 4 });
  if (ctx.dihu) items.push({ id: 'dihu', fan: 4 });
  const fanRaw = items.reduce((a, b) => a + b.fan, 0);
  const fanCharged = Math.min(fanRaw, FAN_CAP);
  return {
    skeleton: value.skeleton,
    items,
    fanRaw,
    fanCharged,
    points: scoreOf(fanRaw, baseScore),
  };
}

export function describeScore(s: WinScore): string {
  return s.items
    .map((it) =>
      it.id === 'gen' ? `根×${it.fan}` : it.fan > 0 ? `${FAN_NAME[it.id]}` : FAN_NAME[it.id],
    )
    .join(' · ');
}
