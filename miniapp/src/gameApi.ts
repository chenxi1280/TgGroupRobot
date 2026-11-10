import { initData } from '@tma.js/sdk-react';

export type Game = 'blackjack' | 'k3';
export type Round = { id: number; status: string; settle_at: string | null };
type Player = Round & { bet: number; payout: number; player_status: string };
export type BlackjackHand = Player & {
  player: number[];
  dealer: (number | null)[];
  player_total: number;
  dealer_total: number | null;
};
export type Draw = { id: number; dice: number[] | null; label: string | null };
type Common = {
  chat_title: string;
  historical: boolean;
  own_result: boolean;
  enabled: Record<Game, boolean>;
  balance: number;
  balance_label: string;
  max_bet: number;
  server_time: string;
};
export type GameState = Common & (
  | { game: 'blackjack'; round: BlackjackHand | null }
  | {
    game: 'k3';
    round: (Round & { players: number }) | null;
    my_k3: (Player & Draw & { guess: string; fee?: number }) | null;
    fee?: number;
    draw: Draw | null;
    options: { key: string; label: string; multiplier: string }[];
  }
);
export type Move =
  | { action: 'start'; round_id: number; bet: number }
  | { action: 'bet'; round_id: number; target_round_id?: number; bet: number; guess: string; fee: number }
  | { action: 'hit' | 'stand'; round_id: number; card_count: number };

export class GameError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function gameRequest(game: Game, move?: Move, current = false): Promise<GameState> {
  const result = await fetch('/miniapp/api/games/' + game + (current ? '?current=true' : ''), {
    method: move ? 'POST' : 'GET',
    headers: { Authorization: 'tma ' + initData.raw(), 'Content-Type': 'application/json' },
    body: move ? JSON.stringify(move) : undefined,
  });
  const data = await result.json();
  if (!result.ok) throw new GameError(typeof data.detail === 'string' ? data.detail : '游戏暂时不可用', result.status);
  return data;
}
