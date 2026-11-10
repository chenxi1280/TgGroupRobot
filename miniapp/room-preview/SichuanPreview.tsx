import { useEffect, useReducer, useState } from 'react';
import { Table, sichuan } from './deskpark/engine';
import SichuanBoard from './deskpark/web/games/sichuan/SichuanBoard';

const seats = [
  { name: '我', isBot: false },
  { name: '南风', isBot: true },
  { name: '西风', isBot: true },
  { name: '北风', isBot: true },
];

function newTable() {
  return new Table(sichuan, seats, { ...sichuan.defaultOptions, rounds: 1 }, { humanTimeoutMs: null });
}

export function SichuanPreview({ leave }: { leave: () => void }) {
  const [table, setTable] = useState(newTable);
  const [, redraw] = useReducer((version: number) => version + 1, 0);
  useEffect(() => {
    const unsubscribe = table.subscribe(redraw);
    table.start();
    return () => {
      unsubscribe();
      table.stop();
    };
  }, [table]);

  return (
    <SichuanBoard
      ctl={{
        def: sichuan, seat: 0, players: seats, view: table.view(0),
        version: table.version, deadlines: table.deadlines,
        act: (action) => table.act(0, action),
        canRestart: true, restart: () => setTable(newTable()), leave,
      }}
    />
  );
}
