/**
 * 麻将牌（序数牌）基础定义，供各麻将玩法共用。
 *
 * 牌 id 0..107：suitIndex = id // 36（0 万、1 条、2 筒），rank = (id % 36) // 4 + 1，copy = id % 4。
 * 「种类」kind = suitIndex * 9 + rank - 1，取值 0..26，用于计数与牌型分析。
 */

export type MjSuit = 'wan' | 'tiao' | 'tong';

export interface Tile {
  id: number;
  suit: MjSuit;
  rank: number;
}

export const MJ_SUITS: readonly MjSuit[] = ['wan', 'tiao', 'tong'];
export const MJ_SUIT_LABEL: Record<MjSuit, string> = { wan: '万', tiao: '条', tong: '筒' };
export const KINDS = 27;

export function tileOf(id: number): Tile {
  const suitIndex = Math.floor(id / 36);
  return { id, suit: MJ_SUITS[suitIndex], rank: Math.floor((id % 36) / 4) + 1 };
}

/** 108 张序数牌 */
export function createTiles(): Tile[] {
  return Array.from({ length: 108 }, (_, id) => tileOf(id));
}

export function suitIndex(suit: MjSuit): number {
  return MJ_SUITS.indexOf(suit);
}

export function kindOf(t: Pick<Tile, 'suit' | 'rank'>): number {
  return suitIndex(t.suit) * 9 + t.rank - 1;
}

export function kindSuit(kind: number): MjSuit {
  return MJ_SUITS[Math.floor(kind / 9)];
}

export function kindRank(kind: number): number {
  return (kind % 9) + 1;
}

export function kindName(kind: number): string {
  return `${kindRank(kind)}${MJ_SUIT_LABEL[kindSuit(kind)]}`;
}

export function tileName(t: Tile): string {
  return `${t.rank}${MJ_SUIT_LABEL[t.suit]}`;
}

export function countKinds(tiles: readonly Pick<Tile, 'suit' | 'rank'>[]): number[] {
  const c = new Array<number>(KINDS).fill(0);
  for (const t of tiles) c[kindOf(t)]++;
  return c;
}

/** 手牌排序：按花色（定缺花色放最后）、点数、id */
export function sortTiles(tiles: readonly Tile[], que: MjSuit | null = null): Tile[] {
  const order = (s: MjSuit) => (s === que ? 9 : suitIndex(s));
  return [...tiles].sort((a, b) => order(a.suit) - order(b.suit) || a.rank - b.rank || a.id - b.id);
}

export function suitsOf(tiles: readonly Pick<Tile, 'suit'>[]): Set<MjSuit> {
  return new Set(tiles.map((t) => t.suit));
}
