import { lazy, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { initData } from '@tma.js/sdk-react';
import { init } from './init';
import { Verify } from './Verify';
import { Games } from './Games';
import './style.css';

if (import.meta.env.DEV) await import('./mockEnv');

const Rooms = lazy(() => import('./Rooms'));

const root = ReactDOM.createRoot(document.getElementById('root')!);
try {
  init();
  const scene = initData.startParam() || '';
  const game = /^game_(blackjack|k3)_[1-9][0-9]{0,15}$/.exec(scene);
  const room = /^(?:rooms_[1-9][0-9]{0,15}|room_[1-9][0-9]{0,15}_([1-9][0-9]{0,9})(?:_([1-9][0-9]?))?)$/.exec(scene);
  if (room) root.render(<Suspense fallback={<main>正在打开游戏房间…</main>}>
    <Rooms initialRoom={room[1] ? Number(room[1]) : undefined} initialHand={room[2] ? Number(room[2]) : undefined} />
  </Suspense>);
  else if (game) root.render(<Games initial={game[1] === 'k3' ? 'k3' : 'blackjack'} />);
  else if (scene.startsWith('verify_')) root.render(<Verify token={scene.slice('verify_'.length)} />);
  else throw new Error('请从群内打开');
} catch {
  root.render(<main className="unsupported"><div className="hero-mark">↗</div><h1>在 Telegram 中打开</h1><p>请返回群聊，点击机器人消息下方的验证或游戏按钮。</p></main>);
}
