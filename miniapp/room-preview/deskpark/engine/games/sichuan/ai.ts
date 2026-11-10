import { seatName, withRecommended } from '../../core/ai';
import type { Rng } from '../../core/rng';
import type { AiOption, AiPrompt, Seat } from '../../core/types';
import type { Tile } from '../../mahjong/tiles';
import { MJ_SUIT_LABEL, kindOf, tileName } from '../../mahjong/tiles';
import { sichuanBot } from './bot';
import type { ScAction, ScMeld, ScView } from './index';

const tilesText = (tiles: readonly Tile[]) =>
  tiles.length
    ? [...tiles]
        .sort((a, b) => kindOf(a) - kindOf(b))
        .map(tileName)
        .join(' ')
    : '（无）';
const meldText = (m: ScMeld) => `${m.type === 'kong' ? '杠' : '碰'}${tileName(m.tiles[0])}`;

export function scAiPrompt(view: ScView, seat: Seat, rng: Rng): AiPrompt<ScAction> | null {
  const L = view.legal;
  if (!L || L.ready || L.exchange) return null;
  const rec = sichuanBot(view, seat, rng);
  const me = view.players[seat];
  const lines = [
    '四川麻将（血战到底）：只有万、条、筒；必须定缺一门，缺门的牌打完才能胡；一家胡了其余继续。',
  ];
  lines.push(
    `你的手牌：${tilesText(view.hand)}${view.drawn !== null ? `（刚摸到 ${tileName(view.hand.find((t) => t.id === view.drawn) ?? view.hand[0])}）` : ''}`,
  );
  if (me.que) lines.push(`你定缺：${MJ_SUIT_LABEL[me.que]}`);
  if (me.melds.length) lines.push(`你的碰杠：${me.melds.map(meldText).join('，')}`);
  for (const d of [1, 2, 3]) {
    const s = (seat + d) % 4;
    const p = view.players[s];
    const parts = [`${seatName(seat, s, 4)}：手牌 ${p.handCount} 张`];
    if (p.que) parts.push(`缺${MJ_SUIT_LABEL[p.que]}`);
    if (p.melds.length) parts.push(`碰杠 ${p.melds.map(meldText).join(' ')}`);
    if (p.river.length)
      parts.push(
        `最近打出 ${p.river
          .slice(-6)
          .map((r) => tileName(r.tile))
          .join(' ')}`,
      );
    if (p.won) parts.push('已胡');
    lines.push(parts.join('，'));
  }
  lines.push(`牌墙剩 ${view.wallCount} 张。`);

  const options: AiOption<ScAction>[] = [];
  if (L.que) {
    lines.unshift('阶段：定缺（选一门花色，之后必须先把这门打完）。');
    for (const suit of ['wan', 'tiao', 'tong'] as const) {
      const n = view.hand.filter((t) => t.suit === suit).length;
      options.push({
        label: `定缺${MJ_SUIT_LABEL[suit]}（手里有 ${n} 张）`,
        action: { type: 'que', suit },
      });
    }
    return { situation: lines.join('\n'), options: withRecommended(rec, options) };
  }
  if (view.window?.tile) {
    lines.push(
      `${view.window.source !== null ? seatName(seat, view.window.source, 4) : '有人'}打出了 ${tileName(view.window.tile)}，你可以选择：`,
    );
  }
  if (L.hu) options.push({ label: '胡牌', action: { type: 'hu' } });
  if (L.mustHu) return { situation: lines.join('\n'), options: withRecommended(rec, options) };
  if (view.window) {
    if (L.gang.length)
      options.push({ label: `杠 ${tileName(view.window.tile!)}`, action: { type: 'gang' } });
    if (L.peng)
      options.push({ label: `碰 ${tileName(view.window.tile!)}`, action: { type: 'peng' } });
  } else {
    for (const g of L.gang) {
      const t = view.hand.find((x) => x.id === g.tile);
      options.push({
        label: `${g.type === 'an' ? '暗杠' : '补杠'} ${t ? tileName(t) : ''}`,
        action: { type: 'gang', tile: g.tile },
      });
    }
  }
  if (L.pass) options.push({ label: L.hu ? '过（不胡）' : '过', action: { type: 'pass' } });
  const seenKind = new Set<number>();
  for (const id of L.discard) {
    const t = view.hand.find((x) => x.id === id);
    if (!t || seenKind.has(kindOf(t))) continue;
    seenKind.add(kindOf(t));
    options.push({ label: `打出 ${tileName(t)}`, action: { type: 'discard', tile: id } });
  }
  if (!options.length) return null;
  // 推荐的打法可能是同一种牌的另一张：换成候选里的那张
  let r = rec;
  if (rec.type === 'discard') {
    const t = view.hand.find((x) => x.id === rec.tile);
    const same = options.find(
      (o) =>
        o.action.type === 'discard' &&
        t &&
        view.hand.find(
          (x) => x.id === (o.action as { tile: number }).tile && kindOf(x) === kindOf(t),
        ),
    );
    if (same) r = same.action;
  }
  return { situation: lines.join('\n'), options: withRecommended(r, options, 40) };
}
