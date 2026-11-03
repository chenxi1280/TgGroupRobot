import { initData } from '@tma.js/sdk-react';

export type Verification = {
  status: string;
  message: string;
  chat_title?: string;
  mode?: string;
  question?: string;
  agreement?: string;
  expires_at?: string;
  server_time?: string;
};

export async function verifyRequest(token: string, payload?: { action: string; answer: string }): Promise<Verification> {
  const response = await fetch('/miniapp/api/verification', {
    method: payload ? 'POST' : 'GET',
    headers: { Authorization: `tma ${initData.raw()}`, 'Content-Type': 'application/json', 'X-Verification-Token': token },
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请检查验证内容后重试');
  return result;
}
