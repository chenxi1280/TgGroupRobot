import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ToastHost } from './deskpark/web/components/ui';
import { SichuanPreview } from './SichuanPreview';
import { GoldenFlowerPreview } from './GoldenFlowerPreview';
import './deskpark/web/styles/tokens.css';
import './deskpark/web/styles/global.css';
import './deskpark/web/components/components.css';
import './deskpark/web/components/mahjong.css';
import './deskpark/web/screens/table.css';
import './preview.css';

function RoomPreview() {
  const [game, setGame] = useState<'sichuan' | 'golden-flower' | null>(
    new URLSearchParams(location.search).get('game') === 'golden-flower' ? 'golden-flower' : 'sichuan',
  );
  return (
    <main className="table room-preview">
      <header className="table__top room-preview-header">
        <div className="table__title"><strong>牌桌试玩</strong><span>本地预览 · 试玩积分</span></div>
        <div className="room-preview-tabs">
          <button aria-pressed={game === 'sichuan'} onClick={() => setGame('sichuan')}>四川血战</button>
          <button aria-pressed={game === 'golden-flower'} onClick={() => setGame('golden-flower')}>炸金花</button>
        </div>
      </header>
      <div className="board">
        {game === 'sichuan' && <SichuanPreview leave={() => setGame(null)} />}
        {game === 'golden-flower' && <GoldenFlowerPreview />}
        {game === null && <p className="preview-lobby">选择上方的游戏开始试玩</p>}
      </div>
      <ToastHost />
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<RoomPreview />);

Object.assign(window, {
  render_game_to_text: () => JSON.stringify({
    game: document.querySelector('.room-preview-tabs [aria-pressed="true"]')?.textContent,
    status: document.querySelector('.sc-actions, .flower-actions')?.textContent,
    cards: document.querySelectorAll('.sc-handtile, .card-inner.flipped').length,
  }),
});
