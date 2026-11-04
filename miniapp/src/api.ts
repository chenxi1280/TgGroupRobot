import { initData } from '@tma.js/sdk-react';

export type Puzzle = { id: string; background: string; piece: string; width: number; height: number; piece_size: number; top: number };

export class VerificationError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export type Verification = {
  status: string;
  message: string;
  chat_title?: string;
  puzzle?: Puzzle;
  expires_at?: string;
  server_time?: string;
};

export async function verifyRequest(token: string, payload?: { puzzle_id: string; position: number }): Promise<Verification> {
  const response = await fetch('/miniapp/api/verification', {
    method: payload ? 'POST' : 'GET',
    headers: { Authorization: `tma ${initData.raw()}`, 'Content-Type': 'application/json', 'X-Verification-Token': token },
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new VerificationError(typeof result.detail === 'string' ? result.detail : '请检查验证内容后重试', response.status);
  return result;
}
