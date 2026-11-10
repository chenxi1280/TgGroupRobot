import { useState } from 'react';
import CardFace from './golden-flower/components/Cards/CardFace';
import DealingAnimation from './golden-flower/components/Table/DealingAnimation';
import type { GameAction, GameState } from './golden-flower/types/game';
import gameBackground from './golden-flower/assets/game-bg.jpg';

type PreviewState = GameState & { available_actions: GameAction[] };

const actionLabels: Record<GameAction, string> = {
  fold: '弃牌', call: '跟注', raise: '加注', check_cards: '看牌', compare: '比牌',
};
const positions = [{ x: 22, y: 37 }, { x: 78, y: 37 }, { x: 50, y: 69 }];

export function GoldenFlowerPreview() {
  const [game, setGame] = useState<PreviewState | null>(null);
  const [busy, setBusy] = useState(false);
  const [dealing, setDealing] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState('');
  const round = game?.current_round;
  const player = game && round && game.players[round.current_player_index];
  const result = game?.round_history[game.round_history.length - 1];

  async function request(action?: GameAction, target?: string) {
    setBusy(true);
    setError('');
    try {
      const endpoint = action ? 'games/' + game!.game_id + '/moves' : 'games';
      const response = await fetch(import.meta.env.BASE_URL + 'room-preview-api/' + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: action ? JSON.stringify({ action, target_id: target }) : undefined,
      });
      if (!response.ok) throw new Error('试玩请求失败，请检查本地炸金花服务。');
      const state: PreviewState = await response.json();
      setGame(state);
      setComparing(false);
      if (!action) setDealing(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flower-preview" style={{ backgroundImage: 'url(' + gameBackground + ')' }}>
      <div className="flower-info">
        {round ? <><b>底池 {round.pot}</b> · 第 {round.turn_count + 1} 轮 · 当前注 {round.current_bet}</> : '三人试玩 · 在同一台设备轮流操作'}
      </div>
      {game && round && (
        <>
          {game.players.map((seat, index) => (
            <div key={seat.id}
              className={'flower-seat' + (seat.id === player?.id && !result ? ' is-active' : '')}
              style={{ left: positions[index].x + '%', top: positions[index].y + '%' }}>
              <strong>{seat.name}{index === round.dealer_index ? ' · 庄' : ''}</strong>
              <span>{seat.chips} 试玩积分</span>
              <div className="flower-cards">
                {!dealing && [0, 1, 2].map((i) => {
                  const card = (result?.hands_revealed?.[seat.id] ?? seat.hand)?.[i] ?? null;
                  return <CardFace key={i} card={card} faceUp={!!card} size="xs" />;
                })}
              </div>
            </div>
          ))}
          {dealing && (
            <DealingAnimation isDealing={dealing} seatPositions={positions} playerCount={game.players.length}
              onComplete={() => setDealing(false)} />
          )}
        </>
      )}
      <div className="flower-actions">
        <p aria-live="polite">{error || (result ? result.winner_name + ' 赢得 ' + result.pot + ' 分'
          : dealing ? '正在发牌…' : player ? '轮到 ' + player.name : '选择开局开始体验')}</p>
        {!game || result ? (
          <button className="btn btn--primary" disabled={busy} onClick={() => void request()}>
            {result ? '再开一局' : '开局'}
          </button>
        ) : comparing ? (
          <>
            {game.players.filter((p) => p.id !== player?.id && p.status.startsWith('active')).map((p) => (
              <button key={p.id} className="btn" disabled={busy} onClick={() => void request('compare', p.id)}>
                与{p.name}比牌
              </button>
            ))}
            <button className="btn" onClick={() => setComparing(false)}>取消</button>
          </>
        ) : game.available_actions.map((action) => (
          <button key={action} className="btn" disabled={busy || dealing}
            onClick={() => action === 'compare' ? setComparing(true) : void request(action)}>
            {actionLabels[action]}
          </button>
        ))}
      </div>
    </section>
  );
}
