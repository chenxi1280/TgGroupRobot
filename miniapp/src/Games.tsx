import { useEffect, useRef, useState } from 'react';
import { miniApp } from '@tma.js/sdk-react';
import { GameError, gameRequest, type Game, type GameState, type Move, type Round } from './gameApi';
import { BlackjackTable, K3Table } from './GameTables';
import './games.css';

const titles = { blackjack: '黑杰克', k3: '快三' };
const presets = [10, 50, 100];
const readError = (error: unknown) => error instanceof GameError ? error.message : '网络异常，请刷新状态后再操作';

function RoundStatus({ state, remaining }: { state: GameState; remaining: number }) {
  const hand = state.round;
  const my = state.game === 'k3' ? state.my_k3 : state.round;
  const fee = state.game === "k3" ? state.my_k3?.fee ?? 0 : 0;
  if (!my) return <span>{state.game === 'blackjack' ? '选择积分，开始发牌' : '选择玩法和积分，加入本局'}</span>;
  if (my.status === 'finished') {
    const result = { won: '你获胜', lost: '未获胜', push: '平局' }[my.player_status] ?? '已结算';
    return <span>{result} · #{my.id} · 下注 {my.bet} · 返还 {my.payout}{fee > 0 ? " · 台费 " + fee : ""}</span>;
  }
  if (state.game === 'blackjack') {
    return <span>{remaining ? '轮到你 · ' + remaining + ' 秒 · 下注 ' + my.bet : '等待超时结算'}</span>;
  }
  return <span>{hand?.id === my.id && remaining ? '已参与本局 · 下注 ' + my.bet + (fee ? ' · 已扣台费 ' + fee : '') : '等待开奖结算'}</span>;
}

function remainingSeconds(round: Round | null, now: number) {
  return round?.settle_at ? Math.max(0, Math.ceil((Date.parse(round.settle_at) - now) / 1000)) : 0;
}

function Board({ game, onSwitch }: { game: Game; onSwitch: (game: Game) => void }) {
  const [state, setState] = useState<GameState>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [bet, setBet] = useState('10');
  const [guess, setGuess] = useState('big');
  const [now, setNow] = useState(Date.now);
  const inFlight = useRef(false);
  const version = useRef(0);
  const offset = useRef(0);

  const accept = (result: GameState) => {
    offset.current = Date.parse(result.server_time) - Date.now();
    setNow(Date.now() + offset.current);
    setState(result);
  };
  const refresh = async () => {
    if (inFlight.current) return;
    const revision = ++version.current;
    try {
      const result = await gameRequest(game);
      if (version.current === revision) accept(result);
    } catch (cause) {
      if (version.current === revision) setError(readError(cause));
    }
  };
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => setNow(Date.now() + offset.current), 1000);
    const poll = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 8000);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => {
      version.current++;
      window.clearInterval(timer);
      window.clearInterval(poll);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [game]);

  const submit = async (move: Move) => {
    if (inFlight.current) return;
    inFlight.current = true;
    version.current++;
    setBusy(true);
    setError('');
    try { accept(await gameRequest(game, move)); }
    catch (cause) {
      setError(readError(cause));
      inFlight.current = false;
      await refresh();
    }
    finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const remaining = remainingSeconds(state?.round ?? null, now);
  const blackjack = state?.game === 'blackjack' ? state.round : null;
  const k3 = state?.game === 'k3' ? state : null;
  const locked = blackjack?.status === 'player_turn';
  const joined = Boolean(k3?.round && k3.my_k3?.id === k3.round.id);
  const waitDraw = Boolean(k3?.round && !remaining);
  const value = Number(bet);
  const fee = k3?.fee ?? 0;
  const canBet = Boolean(state?.enabled[game] && !joined && !waitDraw &&
    Number.isInteger(value) && value >= 1 && value <= Math.min(state.max_bet, state.balance - fee));

  const open = () => void submit(game === 'blackjack'
    ? { action: 'start', round_id: blackjack?.id ?? 0, bet: value }
    : { action: 'bet', round_id: k3?.my_k3?.id ?? 0, target_round_id: k3?.round?.id, bet: value, guess, fee });
  const play = (action: 'hit' | 'stand') => {
    if (blackjack) void submit({ action, round_id: blackjack.id, card_count: blackjack.player.length });
  };

  if (import.meta.env.DEV) {
    (window as Window & { render_game_to_text?: () => string }).render_game_to_text = () =>
      JSON.stringify({ game, balance: state?.balance, remaining, round: state?.round, draw: k3?.draw, error });
  }

  return <main className="gt-page">
    <div className="gt-shell">
      <div className="gt-header">
        <div className="gt-brand"><span aria-hidden="true">{game === 'blackjack' ? '♠' : '⚄'}</span>
          <div><h1>{titles[game]}</h1><div>{state?.chat_title || '群游戏'}</div></div>
        </div>
        <button type="button" className="gt-close" onClick={() => miniApp.close.ifAvailable()}>返回群聊</button>
      </div>
      <nav className="gt-switch" aria-label="切换游戏">
        {(['blackjack', 'k3'] as const).map(option =>
          <button type="button" key={option} aria-pressed={option === game} disabled={busy}
            onClick={() => onSwitch(option)}>{titles[option]}</button>)}
      </nav>
      <div className="gt-balance">
        <div><span>可用积分</span><small>{state?.balance_label || '群积分'}</small></div>
        <strong>{state ? state.balance.toLocaleString('zh-CN') : '–'}</strong>
      </div>
      {game === 'blackjack' ? <BlackjackTable hand={blackjack} /> : k3 && <K3Table state={k3} remaining={remaining} />}
      <div className="gt-controls">
        <div className="gt-status" aria-live="polite">
          {state ? <RoundStatus state={state} remaining={remaining} /> : '正在读取牌桌状态…'}
        </div>
        {error && <div className="gt-error" role="alert">{error} <button type="button" onClick={() => {
          setError('');
          void refresh();
        }}>刷新</button></div>}
        {locked ? <div className="gt-actions">
          <button type="button" disabled={busy || !remaining} onClick={() => play('hit')}>＋ 要牌</button>
          <button type="button" disabled={busy || !remaining} onClick={() => play('stand')}>停牌</button>
        </div> : state?.enabled[game] && !joined && !waitDraw && <>
          {k3 && <div className="gt-options" aria-label="快三玩法">
            {k3.options.map(option => <button type="button" key={option.key} disabled={busy}
              aria-pressed={guess === option.key} onClick={() => setGuess(option.key)}>
              {option.label}<small>{option.multiplier}×</small>
            </button>)}
          </div>}
          <div className="gt-amount">
            <label htmlFor="game-bet">下注积分</label>
            <input id="game-bet" inputMode="numeric" type="number" min={1} max={state.max_bet}
              value={bet} disabled={busy} onChange={e => setBet(e.target.value)} />
            {presets.map(amount => <button type="button" key={amount} disabled={busy} aria-pressed={value === amount}
              onClick={() => setBet(String(amount))}>{amount}</button>)}
          </div>
          {fee > 0 && <div className="gt-hint">本次台费 {fee} 分 · 确认下注时一并扣除</div>}
          <button className="gt-primary" type="button" disabled={!canBet || busy} onClick={open}>
            {busy ? '处理中…' : game === 'blackjack' ? '发牌' : '确认下注'}
          </button>
          {value + fee > state.balance && <div className="gt-hint">余额不足</div>}
        </>}
        {state && !state.enabled[game] && !locked && <div className="gt-hint">本群暂未开启此游戏</div>}
      </div>
    </div>
  </main>;
}

export function Games({ initial }: { initial: Game }) {
  const [game, setGame] = useState(initial);
  return <Board key={game} game={game} onSwitch={setGame} />;
}
