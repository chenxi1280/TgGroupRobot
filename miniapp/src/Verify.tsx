import { useEffect, useState } from 'react';
import { initData, miniApp } from '@tma.js/sdk-react';
import { verifyRequest, type Verification } from './api';

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
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setError('');
    try { setValue(await verifyRequest(token)); }
    catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { void load(); }, [token]);
  const submit = async (action: string) => {
    setBusy(true); setError('');
    try {
      const result = await verifyRequest(token, { action, answer });
      setValue(previous => ({ ...previous, ...result }));
    } catch (e) { setError((e as Error).message); }
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
        {active && <form onSubmit={event => { event.preventDefault(); void submit(value.mode === 'button' ? 'agree' : 'answer'); }}>
          <div className="divider" />
          <h2>{value.mode === 'button' ? '阅读并同意群规' : value.mode === 'math' ? '回答一道简单算术题' : '输入验证码'}</h2>
          {value.mode === 'button' ? <p className="agreement">{value.agreement}</p> : <>
            <div className="question">{value.question}</div>
            <label htmlFor="answer">你的答案</label>
            <input id="answer" value={answer} onChange={event => setAnswer(event.target.value)} inputMode="numeric" autoComplete="off" maxLength={128} placeholder="在这里输入答案" required />
          </>}
          <button type="submit" disabled={busy}>{busy ? '正在处理…' : value.mode === 'button' ? '同意群规并验证' : '提交验证'}</button>
          {value.mode === 'button' && <button className="quiet" type="button" disabled={busy} onClick={() => void submit('decline')}>不同意，按群规则处理</button>}
        </form>}
        {error && <p role="alert" className="error">{error}</p>}
        {!active && <button disabled={busy} onClick={() => verified || value?.status === 'review' ? miniApp.close() : void load()}>{verified || value?.status === 'review' ? '返回群聊' : '刷新验证状态'}</button>}
      </section>
      <p className="footnote">{active ? '验证完成前暂时无法发言。关闭页面不会暂停计时。' : '如有疑问，请联系群管理员。'}</p>
    </main>
  </>;
}
