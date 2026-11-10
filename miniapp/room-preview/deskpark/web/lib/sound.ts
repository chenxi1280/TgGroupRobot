/**
 * 合成音效（WebAudio），不依赖任何音频文件，体积为零。
 * 音量刻意压低，追求"轻、短、柔"的质感。
 */
type SoundName = 'play' | 'pass' | 'turn' | 'deal' | 'bomb' | 'win' | 'lose' | 'chip' | 'select';

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  try {
    if (!ctx) ctx = new AudioContext();
    if (ctx.state === 'suspended') void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

function tone(
  ac: AudioContext,
  freq: number,
  start: number,
  dur: number,
  gain: number,
  type: OscillatorType = 'sine',
  slideTo?: number,
) {
  const osc = ac.createOscillator();
  const g = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  if (slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, start + dur);
  g.gain.setValueAtTime(0.0001, start);
  g.gain.exponentialRampToValueAtTime(gain, start + 0.008);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(g).connect(ac.destination);
  osc.start(start);
  osc.stop(start + dur + 0.02);
}

function noise(ac: AudioContext, start: number, dur: number, gain: number, freq = 2400) {
  const len = Math.floor(ac.sampleRate * dur);
  const buf = ac.createBuffer(1, len, ac.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len) ** 2;
  const src = ac.createBufferSource();
  src.buffer = buf;
  const filter = ac.createBiquadFilter();
  filter.type = 'bandpass';
  filter.frequency.value = freq;
  filter.Q.value = 0.8;
  const g = ac.createGain();
  g.gain.value = gain;
  src.connect(filter).connect(g).connect(ac.destination);
  src.start(start);
}

export function playSound(name: SoundName): void {
  const ac = audio();
  if (!ac) return;
  const t = ac.currentTime + 0.005;
  switch (name) {
    case 'play':
      noise(ac, t, 0.07, 0.35, 2800);
      tone(ac, 520, t, 0.08, 0.04, 'triangle', 380);
      break;
    case 'select':
      tone(ac, 900, t, 0.04, 0.025, 'sine');
      break;
    case 'deal':
      noise(ac, t, 0.05, 0.18, 3600);
      break;
    case 'pass':
      tone(ac, 330, t, 0.12, 0.04, 'sine', 260);
      break;
    case 'turn':
      tone(ac, 880, t, 0.16, 0.05, 'sine');
      tone(ac, 1320, t + 0.09, 0.22, 0.035, 'sine');
      break;
    case 'chip':
      tone(ac, 2200, t, 0.05, 0.03, 'triangle');
      tone(ac, 2900, t + 0.035, 0.05, 0.02, 'triangle');
      break;
    case 'bomb':
      tone(ac, 140, t, 0.45, 0.22, 'sine', 50);
      noise(ac, t, 0.3, 0.5, 400);
      break;
    case 'win':
      [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
        tone(ac, f, t + i * 0.09, 0.42, 0.05, 'sine'),
      );
      break;
    case 'lose':
      [392, 329.63, 261.63].forEach((f, i) => tone(ac, f, t + i * 0.12, 0.4, 0.04, 'sine'));
      break;
  }
}
