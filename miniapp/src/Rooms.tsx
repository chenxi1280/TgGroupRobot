import { useEffect, useRef, useState } from 'react';
import { miniApp, shareMessage } from '@tma.js/sdk-react';
import { RoomFlower, RoomMahjong } from './RoomTables';
import {
  roomInvite, roomNames, roomRequest, saveGroupRoomSettings,
  type GroupRoomSettings, type InviteTarget, type Lobby, type RoomGame, type RoomView, type Settlement,
} from './roomApi';
import './rooms.css';

type Operation = 'join' | 'start' | 'next' | 'leave' | 'move';

function ResultTable({ result, mine }: { result: Settlement; mine: number | undefined }) {
  return <section className="room-result room-panel" aria-label="结算">
    <p className="room-kicker">本小局积分流水</p>
    <h2>第 {result.number} 小局{result.void ? '已作废' : '结算'}</h2>
    {result.void && <p>本小局游戏投入已退回，台费按开场记录。</p>}
    <table><thead><tr><th>玩家</th><th>本局输赢</th><th>结算余额</th></tr></thead>
      <tbody>{result.rows.map(row => <tr key={row.id}>
        <td>{row.name}{row.id === mine ? '（我）' : ''}</td>
        <td className={row.delta < 0 ? 'room-loss' : 'room-win'}>{row.delta > 0 ? '+' : ''}{row.delta} 分</td>
        <td>{row.balance === null ? '—' : row.balance + ' 分'}</td>
      </tr>)}</tbody></table>
  </section>;
}

function MatchSummary({ room }: { room: RoomView }) {
  return <section className="room-panel room-result" aria-label="整场结算">
    <p className="room-kicker">已完成 {room.results.filter(hand => !hand.void).length} 小局</p>
    <h2>整场结算</h2>
    <table><thead><tr><th>玩家</th><th>小局合计</th><th>台费</th><th>整场净变动</th></tr></thead>
      <tbody>{room.seats.map(seat => {
        const total = room.results.reduce((sum, hand) =>
          sum + (hand.rows.find(row => row.id === seat.id)?.delta ?? 0), 0);
        const net = total - room.fee;
        return <tr key={seat.id}><td>{seat.name}</td><td>{total > 0 ? '+' : ''}{total} 分</td>
          <td>{room.fee} 分</td><td className={net < 0 ? 'room-loss' : 'room-win'}>{net > 0 ? '+' : ''}{net} 分</td></tr>;
      })}</tbody></table>
  </section>;
}

function RoomSettings({ games, onSaved }: { games: Lobby['games']; onSaved: () => void }) {
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState('');
  return <details className="room-panel room-settings">
    <summary>本群房间游戏设置</summary>
    <form key={JSON.stringify(games)} onSubmit={async event => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      const settings = {} as GroupRoomSettings;
      for (const game of Object.keys(roomNames) as RoomGame[]) {
        settings[game] = { enabled: fields.has(game), points: Number(fields.get(game + '-fee')) };
      }
      setSaving(true);
      setFeedback('');
      try {
        await saveGroupRoomSettings(settings);
        setFeedback('本群设置已保存');
        onSaved();
      } catch (cause) {
        setFeedback((cause as Error).message);
      } finally {
        setSaving(false);
      }
    }}>
      <p>台费在房间创建时锁定，玩家开场时扣除。</p>
      {Object.entries(roomNames).map(([game, name]) => <div key={game} className="room-settings-row">
        <label className="room-checkbox">
          <input type="checkbox" name={game} defaultChecked={games[game as RoomGame].enabled} />开启{name}
        </label>
        <label>每人每场台费
          <input name={game + '-fee'} type="number" min={0} max={100000} required
            defaultValue={games[game as RoomGame].points} />
        </label>
      </div>)}
      <button type="submit" disabled={saving}>保存本群设置</button>
      {feedback && <p role="status">{feedback}</p>}
    </form>
  </details>;
}

function CreatePanel({ lobby, create, busy }: {
  lobby: Lobby; create: (settings: object) => void; busy: boolean;
}) {
  const choices = (Object.keys(roomNames) as RoomGame[]).filter(type => lobby.games[type].enabled);
  const [picked, setPicked] = useState<RoomGame>();
  const [base, setBase] = useState(1);
  const [multiplier, setMultiplier] = useState(1);
  const [special, setSpecial] = useState(true);
  if (lobby.mall_open) return <p className="room-panel">本群积分商城已开启，房间游戏暂不可用。</p>;
  if (!choices.length) return <p className="room-panel">本群尚未启用四川血战或炸金花。玩法启用后，群成员可自行创建房间。</p>;
  const game = picked && choices.includes(picked) ? picked : choices[0];
  return <form className="room-panel" onSubmit={event => {
    event.preventDefault();
    create({ game, base, multiplier, special });
  }}>
    <h2>创建房间</h2>
    <div className="room-form">
      <label>游戏<select value={game} onChange={event => setPicked(event.target.value as RoomGame)}>
        {choices.map(type => <option key={type} value={type}>{roomNames[type]}</option>)}
      </select></label>
      <label>底分<input required type="number" min={1} max={100} value={base} onChange={event => setBase(Number(event.target.value))} /></label>
      <label>倍率<select value={multiplier} onChange={event => setMultiplier(Number(event.target.value))}>
        {[1, 2, 5, 10].map(value => <option key={value} value={value}>{value}×</option>)}
      </select></label>
    </div>
    {game === 'zhajinhua' && <label className="room-checkbox"><input type="checkbox" checked={special}
      onChange={event => setSpecial(event.target.checked)} />235 两人比牌吃豹子</label>}
    <p>每人场费 {lobby.games[game].points} 分 · {lobby.games[game].hands} 小局</p>
    {lobby.balance <= 0 && <p>可用群积分为 0，请先获取群积分。</p>}
    <button disabled={busy || lobby.balance <= 0} className="room-primary" type="submit">创建房间</button>
  </form>;
}

function RoomFeeNotice({ room }: { room: RoomView }) {
  if (room.fee_charged) {
    return <aside className="room-fee" role="status">
      <strong>{room.fee ? "本场已扣台费 " + room.fee + " 分" : "本场免台费"}</strong><span>每小局输赢单独结算</span>
    </aside>;
  }
  return <aside className="room-fee" aria-label="费用说明">
    <strong>每人场费 {room.fee} 分</strong>
    <span>加入时不扣费。房主开场后统一扣除，提前结束场费不退。</span>
    <dl>
      <dt>本场小局数</dt><dd>{room.hand_limit}</dd>
      <dt>首小局{room.game === 'sichuan' ? '预扣赔付' : '底注'}</dt><dd>{room.requirement - room.fee} 分</dd>
      <dt>开场至少需要</dt><dd>{room.requirement} 分</dd>
    </dl>
  </aside>;
}

export default function Rooms({ initialRoom, initialHand }: { initialRoom?: number; initialHand?: number }) {
  const [roomId, setRoomId] = useState(initialRoom);
  const [historyNo, setHistoryNo] = useState(initialHand);
  const [room, setRoom] = useState<RoomView>();
  const [lobby, setLobby] = useState<Lobby>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const flight = useRef(false);
  const revision = useRef(0);

  const refresh = async () => {
    if (flight.current) return;
    const current = ++revision.current;
    try {
      if (roomId === undefined) {
        const data = await roomRequest<Lobby>();
        if (revision.current === current) setLobby(data);
      } else {
        const data = await roomRequest<RoomView>(roomId);
        if (revision.current === current) setRoom(data);
      }
    } catch (cause) {
      if (revision.current === current) setError((cause as Error).message);
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 2500);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => {
      revision.current++;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [roomId]);

  const submit = async (id: number | undefined, body: object) => {
    if (flight.current) return;
    flight.current = true;
    revision.current++;
    setBusy(true);
    setError('');
    try {
      const data = await roomRequest<RoomView>(id, body);
      setRoom(data);
      setRoomId(data.id);
      if (id === undefined) setHistoryNo(undefined);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      flight.current = false;
      setBusy(false);
    }
  };

  const invite = async (target: InviteTarget) => {
    if (!room || flight.current) return;
    flight.current = true;
    revision.current++;
    setBusy(true);
    setError('');
    try {
      const result = await roomInvite(room.id, target);
      if (result.message_id) {
        await shareMessage(result.message_id).catch(cause => {
          if (cause.message !== 'USER_DECLINED') setError('私发邀请失败，请重试。');
        });
      }
      if (result.sent) setRoom({ ...room, group_invited: true });
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      flight.current = false;
      setBusy(false);
    }
  };

  const back = () => {
    setRoom(undefined);
    setRoomId(undefined);
    setHistoryNo(undefined);
    setError('');
  };
  const act = (operation: Operation, action?: object) => {
    if (room) void submit(room.id, { operation, version: room.version, action });
  };
  const mine = room?.seat == null ? undefined : room.seats[room.seat].id;
  const selected = room?.results.find(result => result.number === historyNo);
  const recent = room?.results[room.results.length - 1];
  const result = selected ?? (room?.status !== 'playing' ? recent : undefined);
  const owner = room && mine === room.owner_id;

  if (import.meta.env.DEV) Object.assign(window, {
    render_game_to_text: () => JSON.stringify({
      room: room?.id, status: room?.status, fee: room?.fee, paid: room?.fee_charged,
      balance: room?.balance ?? lobby?.balance, settled: recent?.number, error,
    }),
  });

  return <main className="room-app">
    <header className="room-header">
      <div><p className="room-kicker">TG 群游戏 · 积分牌桌</p>
        <h1>{room ? roomNames[room.game] + ' #' + room.id : '游戏房间'}</h1></div>
      <button type="button" onClick={roomId === undefined ? () => miniApp.close.ifAvailable() : back}>
        {roomId === undefined ? '返回群聊' : '大厅'}
      </button>
    </header>
    <div className="room-balance"><span>可用群积分</span><strong>{room?.balance ?? lobby?.balance ?? '—'}</strong></div>
    {error && <p className="room-error" role="alert">{error} <button onClick={() => { setError(''); void refresh(); }}>刷新</button></p>}
    {roomId === undefined && lobby && <>
      {lobby.can_manage && <RoomSettings games={lobby.games} onSaved={() => void refresh()} />}
      <CreatePanel lobby={lobby} create={data => void submit(undefined, data)} busy={busy} />
      <section className="room-panel"><h2>本群房间</h2>
        {!lobby.rooms.length && <p>目前没有房间。</p>}
        {lobby.rooms.map(item => <button className="room-row" key={item.id} onClick={() => setRoomId(item.id)}>
          <strong>{roomNames[item.game]} #{item.id}</strong><span>{item.players} 人 · 场费 {item.fee} 分</span>
        </button>)}
      </section>
    </>}
    {roomId !== undefined && room && <>
      <RoomFeeNotice room={room} />
      {room.status === 'waiting' && <section className="room-panel">
        <h2>等待玩家</h2><p>{room.seats.map(seat => seat.name).join('、')}</p>
        <p>底分 {room.options.base} · 倍率 {room.options.multiplier}×</p>
        {room.seat === null && room.balance <= 0 && <p>可用群积分为 0，请先获取群积分。</p>}
        <div className="room-actions">
          {room.seat === null && <button className="room-primary" disabled={busy || room.balance <= 0}
            onClick={() => act('join')}>加入房间</button>}
          {owner && <button className="room-primary"
            disabled={busy || room.balance < room.requirement || room.players < (room.game === 'sichuan' ? 4 : 2)}
            onClick={() => act('start')}>开场并扣除台费</button>}
          {room.seat !== null && <button disabled={busy} onClick={() => act('leave')}>离座</button>}
        </div>
        {owner && <div className="room-actions" aria-label="邀请玩家">
          <button disabled={busy || room.group_invited} onClick={() => void invite('group')}>
            {room.group_invited ? '已发到本群' : '发到本群'}
          </button>
          <button disabled={busy || !shareMessage.isAvailable()} onClick={() => void invite('private')}>私发好友</button>
        </div>}
      </section>}
      {room.status === 'playing' && room.table && !selected &&
        (room.game === 'sichuan' ? <RoomMahjong room={room} move={action => act('move', action)} />
          : <RoomFlower room={room} move={action => act('move', action)} busy={busy} />)}
      {room.status === 'playing' && room.seat === null && <p className="room-panel">本场已开场，请等待下一场。</p>}
      {room.status === 'closed' && room.results.length > 0 && <MatchSummary room={room} />}
      {result && <ResultTable result={result} mine={mine} />}
      {selected && room.status === 'playing' && <button onClick={() => setHistoryNo(undefined)}>回到当前牌桌</button>}
      {room.results.length > 0 && <nav className="room-history" aria-label="小局记录">
        {room.results.map(hand => <button key={hand.number} onClick={() => setHistoryNo(hand.number)}>第 {hand.number} 局</button>)}
      </nav>}
      {room.status === 'between' && room.seat !== null && <div className="room-actions">
        {owner ? <button className="room-primary" disabled={busy} onClick={() => {
          setHistoryNo(undefined); act('next');
        }}>开始下一小局</button> : <span>等待房主开启下一小局</span>}
        {owner && <button disabled={busy} onClick={() => act('leave')}>结束本场</button>}
      </div>}
      {room.status === 'closed' && <div className="room-actions">
        <strong>本场已结束</strong>
        <button className="room-primary" disabled={busy} onClick={back}>返回大厅创建新场</button>
      </div>}
    </>}
  </main>;
}
