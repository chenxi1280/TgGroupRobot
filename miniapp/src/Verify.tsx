import { useEffect, useState } from 'react';
import { initData, miniApp } from '@tma.js/sdk-react';
import { VerificationError, verifyRequest, type Verification } from './api';
import { SliderPuzzle } from './SliderPuzzle';

function Remaining({ value }: { value: Verification }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const remaining = Date.parse(value.expires_at!) - Date.parse(value.server_time!);
    const end = Date.now() + remaining;
    const tick = () => setSeconds(Math.max(0, Math.ceil((end - Date.now()) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [value.expires_at, value.server_time]);
  return <span className="timer">剩余 {seconds} 秒</span>;
}

export function Verify({ token }: { token: string }) {
  const [value, setValue] = useState<Verification>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setError('');
    try { setValue(await verifyRequest(token)); }
    catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { void load(); }, [token]);
  const submit = async (position: number) => {
    setBusy(true); setError('');
    try {
      const result = await verifyRequest(token, { position, puzzle_id: value!.puzzle!.id });
      setValue(previous => ({ ...previous, ...result }));
    } catch (e) {
      if (e instanceof VerificationError && e.status === 422) await load();
      setError((e as Error).message);
    }
    finally { setBusy(false); }
  };
  const active = value?.status === 'pending';
  const verified = value?.status === 'verified';
  return <>
    <header><span className="brand-mark">✓</span><span>群验证</span><span className="telegram">TELEGRAM</span></header>
    <main>
      <div className={`hero-mark ${verified ? 'success' : ''}`}>{verified ? '✓' : '◇'}</div>
      <p className="eyebrow">{value?.chat_title || '欢迎加入'}</p>
      <h1>{verified ? '验证完成' : active ? '完成验证，开始交流' : '入群身份验证'}</h1>
      <p className="intro">{value?.message || '正在读取你的验证信息…'}</p>
      <section className="card" aria-busy={busy}>
        <div className="identity"><span className="avatar">{initData.user()?.first_name?.slice(0, 1) || '你'}</span>
          <div><strong>{initData.user()?.first_name}</strong><small>当前 Telegram 账号</small></div>
          {active && <Remaining value={value} />}
        </div>
        {active && value.puzzle && <>
          <div className="divider" />
          <h2>拖动拼图完成验证</h2>
          <SliderPuzzle key={value.puzzle.id} puzzle={value.puzzle} busy={busy} onSubmit={position => void submit(position)} />
        </>}
        {error && <p role="alert" className="error">{error}</p>}
        {!active && <button disabled={busy} onClick={() => verified || value?.status === 'review' ? miniApp.close() : void load()}>{verified || value?.status === 'review' ? '返回群聊' : '刷新验证状态'}</button>}
      </section>
      <p className="footnote">{active ? '验证完成前暂时无法发言。关闭页面不会暂停计时。' : '如有疑问，请联系群管理员。'}</p>
    </main>
  </>;
}
