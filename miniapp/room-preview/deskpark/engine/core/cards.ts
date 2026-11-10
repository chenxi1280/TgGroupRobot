/**
 * 通用扑克牌定义。
 *
 * rank 采用"自然点数"：2..10，J=11，Q=12，K=13，A=14；小王=16，大王=17。
 * 各玩法再把自然点数映射成自己的大小顺序（例如斗地主里 2 比 A 大）。
 */

export type Suit = 'S' | 'H' | 'C' | 'D' | 'J';

export interface Card {
  /** 一副或多副牌中唯一的 id */
  id: number;
  suit: Suit;
  rank: number;
}

export const SUITS: readonly Suit[] = ['S', 'H', 'C', 'D'];
export const SMALL_JOKER = 16;
export const BIG_JOKER = 17;

export const SUIT_SYMBOL: Record<Suit, string> = {
  S: '♠',
  H: '♥',
  C: '♣',
  D: '♦',
  J: '',
};

export const SUIT_NAME: Record<Suit, string> = {
  S: '黑桃',
  H: '红桃',
  C: '梅花',
  D: '方块',
  J: '',
};

export function rankLabel(rank: number): string {
  switch (rank) {
    case 11:
      return 'J';
    case 12:
      return 'Q';
    case 13:
      return 'K';
    case 14:
    case 1:
      return 'A';
    case SMALL_JOKER:
      return '小王';
    case BIG_JOKER:
      return '大王';
    default:
      return String(rank);
  }
}

export function cardLabel(card: Card): string {
  if (card.suit === 'J') return rankLabel(card.rank);
  return SUIT_SYMBOL[card.suit] + rankLabel(card.rank);
}

export function isJoker(card: Card): boolean {
  return card.suit === 'J';
}

export function isRedCard(card: Card): boolean {
  return card.suit === 'H' || card.suit === 'D' || (card.suit === 'J' && card.rank === BIG_JOKER);
}

/** 生成若干副牌（默认含大小王）。 */
export function createDeck(decks = 1, withJokers = true): Card[] {
  const cards: Card[] = [];
  let id = 0;
  for (let d = 0; d < decks; d++) {
    for (const suit of SUITS) {
      for (let rank = 2; rank <= 14; rank++) cards.push({ id: id++, suit, rank });
    }
    if (withJokers) {
      cards.push({ id: id++, suit: 'J', rank: SMALL_JOKER });
      cards.push({ id: id++, suit: 'J', rank: BIG_JOKER });
    }
  }
  return cards;
}

const SUIT_ORDER: Record<Suit, number> = { J: 4, S: 3, H: 2, C: 1, D: 0 };

/** 按给定的取值函数从大到小排序（同值按花色），返回新数组。 */
export function sortCards(cards: readonly Card[], value: (c: Card) => number): Card[] {
  return [...cards].sort(
    (a, b) => value(b) - value(a) || SUIT_ORDER[b.suit] - SUIT_ORDER[a.suit] || a.id - b.id,
  );
}

/** 从 hand 中移除 ids 指定的牌，若有牌不在手中则返回 null。 */
export function removeCards(hand: readonly Card[], ids: readonly number[]): Card[] | null {
  const want = new Set(ids);
  if (want.size !== ids.length) return null;
  const rest = hand.filter((c) => !want.has(c.id));
  if (rest.length !== hand.length - ids.length) return null;
  return rest;
}

/** 从 hand 中按 id 取出牌对象，有缺失时返回 null。 */
export function pickCards(hand: readonly Card[], ids: readonly number[]): Card[] | null {
  const byId = new Map(hand.map((c) => [c.id, c]));
  const out: Card[] = [];
  const seen = new Set<number>();
  for (const id of ids) {
    const c = byId.get(id);
    if (!c || seen.has(id)) return null;
    seen.add(id);
    out.push(c);
  }
  return out;
}

/** 统计每个值出现的次数。 */
export function countBy<T>(items: readonly T[], key: (t: T) => number): Map<number, number> {
  const m = new Map<number, number>();
  for (const it of items) {
    const k = key(it);
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return m;
}
