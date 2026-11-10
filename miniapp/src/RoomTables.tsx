import { useEffect, useMemo, useState } from 'react';
import { sichuan, type sc } from '../room-preview/deskpark/engine';
import SichuanBoard from '../room-preview/deskpark/web/games/sichuan/SichuanBoard';
import { ToastHost } from '../room-preview/deskpark/web/components/ui';
import CardFace from '../room-preview/golden-flower/components/Cards/CardFace';
import DealingAnimation from '../room-preview/golden-flower/components/Table/DealingAnimation';
import type { FlowerTableView, RoomView } from './roomApi';
import '../room-preview/deskpark/web/styles/tokens.css';
import '../room-preview/deskpark/web/components/components.css';
import '../room-preview/deskpark/web/components/mahjong.css';
import '../room-preview/deskpark/web/screens/table.css';
import '../room-preview/preview.css';

function useRemaining(room: RoomView) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const duration = Date.parse(room.deadline ?? '') - Date.parse(room.server_time);
    const ends = Date.now() + duration;
    const update = () => setSeconds(Math.max(0, Math.ceil((ends - Date.now()) / 1000)));
    update();
    const timer = window.setInterval(update, 250);
    return () => window.clearInterval(timer);
  }, [room.deadline, room.server_time]);
  return seconds;
}

export function RoomMahjong({ room, move, busy }: { room: RoomView; move: (action: object) => void; busy: boolean }) {
  const remaining = useRemaining(room);
  const table = room.table as sc.ScView;
  return <div className="room-mahjong room-preview">
    <p className="room-turn">操作剩余 <output aria-label="操作剩余时间">{remaining} 秒</output></p>
    <SichuanBoard showResult={false} displayUnit={room.unit} ctl={{
      def: sichuan, view: table, seat: room.seat, players: room.seats, version: room.version,
      deadlines: {}, canRestart: false, restart() {}, leave() {},
      act(action) {
        if (busy || !remaining) return busy ? "操作提交中" : "等待牌桌更新";
        move(action);
        return null;
      },
    }} />
    <ToastHost />
  </div>;
}

const positions = [
  { x: 50, y: 73 }, { x: 25, y: 46 }, { x: 25, y: 17 },
  { x: 75, y: 17 }, { x: 75, y: 46 }, { x: 83, y: 73 },
];

export function RoomFlower({
  room, move, busy,
}: { room: RoomView; move: (action: object) => void; busy: boolean }) {
  const table = room.table as FlowerTableView;
  const remaining = useRemaining(room);
  const [dealing, setDealing] = useState(true);
  const [choosing, setChoosing] = useState(false);
  const hand = room.results.length + 1;
  useEffect(() => { setDealing(true); setChoosing(false); }, [room.id, hand]);
  const seats = useMemo(() => room.seats.map((_, index) =>
    positions[(index - (room.seat ?? 0) + room.seats.length) % room.seats.length]),
  [room.seat, room.seats.length]);
  const legal = table.legal;
  const play = (type: string, target?: number) => {
    setChoosing(false);
    move({ type, target });
  };
  const locked = busy || dealing || !remaining;
  return <section aria-label="炸金花牌桌">
    <div className="room-flower flower-preview">
      <div className="flower-info">第 {table.round} 轮 · 底池 {table.pot} · 当前注 {table.current_bet}</div>
      {table.players.map((player, index) => <div className={'flower-seat' + (table.turn === index ? ' is-active' : '')}
        key={room.seats[index].id} style={{ left: seats[index].x + '%', top: seats[index].y + '%' }}>
        <strong>{room.seats[index].name}{index === table.dealer ? ' · 庄' : ''}</strong>
        <span>{player.status === 'folded' ? '已弃牌' : player.status === 'compare_lost' ? '比牌出局' : '投入 ' + player.bet}</span>
        <div className="flower-cards">{!dealing && [0, 1, 2].map(i =>
          <CardFace key={i} card={player.cards?.[i] ?? null} faceUp={!!player.cards} size="xs" />,
        )}</div>
      </div>)}
      {dealing && <DealingAnimation isDealing seatPositions={seats} playerCount={seats.length}
        onComplete={() => setDealing(false)} />}
    </div>
    <p className="room-turn" aria-live="polite">{dealing ? '正在发牌…' : '轮到 ' + room.seats[table.turn].name} · 剩余 <output aria-label="操作剩余时间">{remaining} 秒</output></p>
    <div className="room-actions">
      {legal.look && <button disabled={locked} onClick={() => play('look')}>看牌</button>}
      {legal.fold && <button disabled={locked} onClick={() => play('fold')}>弃牌</button>}
      {legal.call !== undefined && <button disabled={locked} onClick={() => play('call')}>跟注</button>}
      {legal.raises?.map(value => <button key={value} disabled={locked} onClick={() => play('raise', value)}>加至 {value}</button>)}
      {!!legal.compare?.length && <button disabled={locked} onClick={() => setChoosing(!choosing)}>比牌</button>}
      {choosing && legal.compare?.map(index =>
        <button key={index} disabled={locked} onClick={() => play('compare', index)}>与{room.seats[index].name}比牌</button>,
      )}
    </div>
  </section>;
}
