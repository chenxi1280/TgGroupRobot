import type { Rng } from '../../core/rng';
import type { Seat } from '../../core/types';
import { shanten } from '../../mahjong/analysis';
import type { MjSuit, Tile } from '../../mahjong/tiles';
import { KINDS, MJ_SUITS, countKinds, kindOf, kindRank, kindSuit } from '../../mahjong/tiles';
import type { ScAction, ScView } from './index';

/**
 * 四川麻将电脑玩家：
 * - 换三张 / 定缺：选最弱的一门（张数少、连接差）；
 * - 出牌：先打缺门；否则选使向听数最小、有效进张最多的牌，并略微倾向做清一色；
 * - 碰 / 杠：只在不拖慢向听时进行；能胡就胡。
 */

/** 一张牌和同门其他牌的关系：对子 2、连张 1、隔一张 0.5 */
export function connectivity(tiles: Tile[], t: Tile): number {
  let s = 0;
  for (const o of tiles) {
    if (o.id === t.id || o.suit !== t.suit) continue;
    const d = Math.abs(o.rank - t.rank);
    if (d === 0) s += 2;
    else if (d === 1) s += 1;
    else if (d === 2) s += 0.5;
  }
  return s;
}

/** 一门牌有多「弱」：张数越少、越散越弱（换三张、定缺都挑最弱的一门） */
export function suitWeakness(hand: Tile[], suit: MjSuit): number {
  const ts = hand.filter((t) => t.suit === suit);
  return ts.length * 10 + ts.reduce((a, t) => a + connectivity(ts, t), 0);
}

export function chooseExchange(hand: Tile[]): number[] {
  const suits = MJ_SUITS.filter((s) => hand.filter((t) => t.suit === s).length >= 3);
  const suit = [...suits].sort((a, b) => suitWeakness(hand, a) - suitWeakness(hand, b))[0];
  const ts = hand.filter((t) => t.suit === suit);
  return [...ts]
    .sort((a, b) => connectivity(ts, a) - connectivity(ts, b) || a.id - b.id)
    .slice(0, 3)
    .map((t) => t.id);
}

export function chooseQue(hand: Tile[]): MjSuit {
  return [...MJ_SUITS].sort((a, b) => suitWeakness(hand, a) - suitWeakness(hand, b))[0];
}

/** 去掉缺门后的计数 */
function usefulCounts(tiles: Tile[], que: MjSuit | null): number[] {
  return countKinds(que ? tiles.filter((t) => t.suit !== que) : tiles);
}

function evalDiscard(counts: number[], melds: number, visible: number[], que: MjSuit | null) {
  const s = shanten(counts, melds);
  let ukeire = 0;
  for (let k = 0; k < KINDS; k++) {
    if (que && kindSuit(k) === que) continue;
    const left = 4 - visible[k];
    if (left <= 0) continue;
    counts[k]++;
    if (shanten(counts, melds) < s) ukeire += left;
    counts[k]--;
  }
  return { s, ukeire };
}

export function sichuanBot(view: ScView, seat: Seat, rng: Rng): ScAction {
  const L = view.legal;
  if (!L) return { type: 'pass' };
  if (L.ready) return { type: 'ready' };
  if (L.exchange) return { type: 'exchange', tiles: chooseExchange(view.hand) };
  if (L.que) return { type: 'que', suit: chooseQue(view.hand) };
  if (L.hu) return { type: 'hu' };

  const me = view.players[seat];
  const que = me.que;
  const hand = view.hand;
  const melds = me.melds.length;
  const visible = view.visible;

  if (view.window) {
    const tile = view.window.tile!;
    const kind = kindOf(tile);
    const base = usefulCounts(hand, que);
    const now = shanten(base, melds);
    if (L.gang.length) {
      const c = [...base];
      c[kind] = 0;
      if (shanten(c, melds + 1) <= now) return { type: 'gang' };
    }
    if (L.peng) {
      const c = [...base];
      c[kind] -= 2;
      // 碰后需要再打一张：取最好的打法
      let best = 99;
      for (let k = 0; k < KINDS; k++) {
        if (c[k] === 0) continue;
        c[k]--;
        best = Math.min(best, shanten(c, melds + 1));
        c[k]++;
      }
      const pairs = base.filter((n) => n >= 2).length;
      if (best < now || (best === now && pairs >= 3 && rng.next() < 0.6)) return { type: 'peng' };
    }
    return { type: 'pass' };
  }

  // 自己的回合
  const qTiles = que ? hand.filter((t) => t.suit === que) : [];
  if (qTiles.length) {
    const pick = [...qTiles].sort(
      (a, b) =>
        connectivity(qTiles, a) - connectivity(qTiles, b) ||
        Math.abs(5 - b.rank) - Math.abs(5 - a.rank),
    )[0];
    return { type: 'discard', tile: pick.id };
  }

  const counts = usefulCounts(hand, que);
  if (L.gang.length) {
    for (const g of L.gang) {
      const t = hand.find((x) => x.id === g.tile)!;
      const k = kindOf(t);
      const c = [...counts];
      if (g.type === 'an') {
        c[k] = 0;
        if (shanten(c, melds + 1) <= shanten(counts, melds) - 0)
          return { type: 'gang', tile: g.tile };
      } else {
        c[k] -= 1;
        // 巴杠后向听不变即可
        if (shanten(c, melds) <= shanten(counts, melds)) return { type: 'gang', tile: g.tile };
      }
    }
  }

  // 向清一色靠拢：一门占多数（含副露 ≥ 9 张）时，同向听下优先打掉另一门
  const suitCount = new Map<MjSuit, number>();
  for (const t of [...hand, ...me.melds.flatMap((m) => m.tiles)]) {
    if (t.suit !== que) suitCount.set(t.suit, (suitCount.get(t.suit) ?? 0) + 1);
  }
  const sorted = [...suitCount.entries()].sort((a, b) => a[1] - b[1]);
  const minorSuit =
    suitCount.size === 2 && (sorted[0][1] <= 3 || sorted[1][1] >= 9) ? sorted[0][0] : null;
  const minorWeight = minorSuit ? (sorted[1][1] >= 10 ? 28 : 12) : 0;

  let best: { id: number; score: number } | null = null;
  const tried = new Set<number>();
  for (const id of L.discard) {
    const t = hand.find((x) => x.id === id)!;
    const k = kindOf(t);
    if (tried.has(k)) continue;
    tried.add(k);
    const c = [...counts];
    c[k]--;
    const { s, ukeire } = evalDiscard(c, melds, visible, que);
    const r = kindRank(k);
    let score = s * 1000 - ukeire * 10;
    if (r === 1 || r === 9) score -= 3;
    if (minorSuit && t.suit === minorSuit) score -= minorWeight;
    score += rng.next();
    if (!best || score < best.score) best = { id, score };
  }
  return { type: 'discard', tile: best!.id };
}
