import type { CSSProperties } from 'react';
import type { BlackjackHand, Draw, GameState } from './gameApi';

const suits = ['♠', '♥', '♣', '♦'];
const pips = [[], [4], [0, 8], [0, 4, 8], [0, 2, 6, 8], [0, 2, 4, 6, 8], [0, 2, 3, 5, 6, 8]];
const animation = (index: number) => ({ '--card-delay': Math.min(index, 5) * 75 + 'ms' } as CSSProperties);

function Cards({ cards, round, dealer }: { cards: (number | null)[]; round: number; dealer: boolean }) {
  return <div className="gt-cards" aria-label={dealer ? '庄家手牌' : '我的手牌'}>
    {cards.map((value, index) => {
      const suitIndex = (round + index + (dealer ? 1 : 0)) % suits.length;
      const suit = suits[suitIndex];
      const rank = value === 1 ? 'A' : value;
      const label = value === null ? '盖牌' : String(rank) + suit;
      return <div key={round + ':' + index} className="gt-card-slot" style={animation(index + (dealer ? 1 : 0))}>
        <div className={'gt-card ' + (dealer && index === 1 ? 'gt-flip' : '')}
          data-revealed={value !== null} role="img" aria-label={label}>
          <div className={'gt-face ' + (suitIndex % 2 ? 'gt-red' : '')} aria-hidden="true">
            <span className="gt-corner">{rank}<small>{suit}</small></span>
            <span className="gt-suit">{suit}</span>
            <span className="gt-corner gt-corner-bottom">{rank}<small>{suit}</small></span>
          </div>
          {(value === null || (dealer && index === 1)) &&
            <div className="gt-back" aria-hidden="true"><span>♠</span></div>}
        </div>
      </div>;
    })}
  </div>;
}

export function BlackjackTable({ hand }: { hand: BlackjackHand | null }) {
  return <div className="gt-felt gt-blackjack">
    <div className="gt-hand">
      <div className="gt-seat">庄家 <output aria-label="庄家点数">{hand?.dealer_total ?? '？'}</output></div>
      {hand ? <Cards cards={hand.dealer} round={hand.id} dealer /> : <div className="gt-placeholders" aria-hidden="true"><i /><i /></div>}
    </div>
    <div className="gt-center"><span>21</span><small>{hand ? '牌局 #' + hand.id : '等待发牌'}</small></div>
    <div className="gt-hand">
      {hand ? <Cards cards={hand.player} round={hand.id} dealer={false} /> : <div className="gt-placeholders" aria-hidden="true"><i /><i /></div>}
      <div className="gt-seat">你 <output aria-label="你的点数">{hand?.player_total ?? '–'}</output></div>
    </div>
  </div>;
}

function Dice({ draw }: { draw: Draw | null }) {
  if (!draw?.dice?.length) return <div className="gt-dice" aria-label="等待开奖">
    {[0, 1, 2].map(i => <div className="gt-die gt-die-empty" key={i}>?</div>)}
  </div>;
  return <div className="gt-dice" aria-label="开奖骰子">
    {draw.dice.map((value, index) => <div className="gt-die" role="img" aria-label={value + ' 点'}
      key={draw.id + ':' + index} style={animation(index)}>
      {Array.from({ length: 9 }, (_, pip) =>
        <i key={pip} data-on={pips[value]?.includes(pip) ?? false} />)}
    </div>)}
  </div>;
}

export function K3Table({ state, remaining }: { state: Extract<GameState, { game: 'k3' }>; remaining: number }) {
  const draw = state.draw;
  return <div className="gt-felt gt-k3-table">
    <div className="gt-k3-round">
      <span>{state.round ? '第 ' + state.round.id + ' 局 · ' + state.round.players + ' 人' : '等待下一局'}</span>
      <output aria-label="剩余秒数">{state.round ? remaining + ' 秒' : '–'}</output>
    </div>
    <Dice draw={draw} />
    <div className="gt-draw">{draw ? '上局 #' + draw.id + ' · ' + (draw.label || '已开奖') : '第一局开奖后显示骰子'}</div>
  </div>;
}
