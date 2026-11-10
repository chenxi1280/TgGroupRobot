import type { ReactNode } from 'react';

type Player = { name: string; avatar?: string };

export function Avatar({ name, avatar, size }: Player & { size: number }) {
  return <span className="preview-avatar" style={{ width: size, height: size }}>{avatar || name[0]}</span>;
}

interface SeatProps {
  player: Player;
  active: boolean;
  deadline?: number;
  size: number;
  layout: 'row' | 'column';
  tag?: string;
  sub: ReactNode;
  children: ReactNode;
}

export function Seat({ player, active, size, layout, tag, sub, children }: SeatProps) {
  return (
    <div className={'seat seat--' + layout + (active ? ' is-active' : '')}>
      <div className="seat__avatar">
        <Avatar {...player} size={size} />
        {tag && <span className="seat__tag">{tag}</span>}
        {children}
      </div>
      <div className="seat__meta">
        <span className="seat__name">{player.name}</span>
        <span className="seat__sub">{sub}</span>
      </div>
    </div>
  );
}
