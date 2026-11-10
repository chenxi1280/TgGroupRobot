import type { Card } from './cards';
import { cardLabel } from './cards';
import type { AiOption } from './types';

/** 牌面文字，例如「♠A ♥K 小王」 */
export function cardsText(cards: readonly Card[]): string {
  return cards.length ? cards.map(cardLabel).join(' ') : '（无）';
}

/** 去重并限制数量：保留第一次出现的动作（第 1 个是推荐动作，始终保留） */
export function uniqueOptions<A>(options: AiOption<A>[], max = 32): AiOption<A>[] {
  const seen = new Set<string>();
  const out: AiOption<A>[] = [];
  for (const o of options) {
    const key = JSON.stringify(o.action);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(o);
    if (out.length >= max) break;
  }
  return out;
}

/** 推荐动作排第一，并在文字上标注 */
export function withRecommended<A>(
  recommended: A,
  options: AiOption<A>[],
  max = 32,
): AiOption<A>[] {
  const key = JSON.stringify(recommended);
  const hit = options.find((o) => JSON.stringify(o.action) === key);
  const first = { label: `${hit?.label ?? '规则建议'}（规则电脑的建议）`, action: recommended };
  return uniqueOptions([first, ...options], max);
}

/** 相对座位称呼 */
export function seatName(me: number, other: number, n: number, names?: readonly string[]): string {
  if (other === me) return '你';
  const d = (other - me + n) % n;
  const rel =
    n === 3 ? (d === 1 ? '下家' : '上家') : n === 4 ? ['', '下家', '对家', '上家'][d] : `${d} 号位`;
  return names?.[other] ? `${rel}「${names[other]}」` : rel;
}
