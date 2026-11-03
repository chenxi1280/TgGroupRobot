import ReactDOM from 'react-dom/client';
import { initData } from '@tma.js/sdk-react';
import { init } from './init';
import { Verify } from './Verify';
import './style.css';

if (import.meta.env.DEV) await import('./mockEnv');

const root = ReactDOM.createRoot(document.getElementById('root')!);
try {
  init();
  const scene = initData.startParam() || '';
  if (!scene.startsWith('verify_')) throw new Error('请点击群内「点击验证」按钮，打开本人的验证页面');
  root.render(<Verify token={scene.slice('verify_'.length)} />);
} catch {
  root.render(<main className="unsupported"><div className="hero-mark">↗</div><h1>在 Telegram 中打开</h1><p>请返回群聊，点击机器人消息下方的「点击验证」，打开本人的验证页面。</p></main>);
}
