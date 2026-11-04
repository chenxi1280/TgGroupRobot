import { useState } from 'react';
import type { Puzzle } from './api';

export function SliderPuzzle({ puzzle, busy, onSubmit }: { puzzle: Puzzle; busy: boolean; onSubmit: (position: number) => void }) {
  const [position, setPosition] = useState(0);
  return <div className="puzzle">
    <div className="puzzle-image" style={{ aspectRatio: `${puzzle.width} / ${puzzle.height}` }}>
      <img src={puzzle.background} alt="带缺口的验证图片" draggable={false} />
      <img className="puzzle-piece" src={puzzle.piece} alt="可移动拼图" draggable={false}
        style={{ width: `${puzzle.piece_size / puzzle.width * 100}%`, left: `${position / puzzle.width * 100}%`, top: `${puzzle.top / puzzle.height * 100}%` }} />
    </div>
    <label className="slider-label" htmlFor="puzzle-slider">向右拖动滑块，对齐后松开</label>
    <input id="puzzle-slider" className="puzzle-slider" type="range" min={0} max={puzzle.width - puzzle.piece_size}
      value={position} step={1} disabled={busy} aria-label="拖动滑块，将拼图对齐缺口"
      onChange={event => setPosition(Number(event.target.value))}
      onPointerUp={event => { if (!busy) onSubmit(Number(event.currentTarget.value)); }}
      onPointerCancel={() => setPosition(0)}
      onKeyUp={event => { if (!busy && event.key === 'Enter') onSubmit(position); }} />
    <p className="slider-hint">{busy ? '正在验证…' : '也可用方向键调整，按 Enter 验证'}</p>
  </div>;
}
