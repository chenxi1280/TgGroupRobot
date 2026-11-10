import { initData } from '@tma.js/sdk-react';
import type { sc } from '../room-preview/deskpark/engine';
import type { Card } from '../room-preview/golden-flower/types/game';

export const roomNames = { sichuan: '四川血战', zhajinhua: '炸金花' };
export type RoomGame = keyof typeof roomNames;
export type FeeOption = { enabled: boolean; points: number; hands: number };
export type RoomOptions = { base: number; multiplier: number; special: boolean };
export type RoomSummary = {
  id: number; game: RoomGame; status: 'waiting' | 'playing' | 'between' | 'closed';
  players: number; fee: number; hand_limit: number; unit: number;
};
type Seat = { id: number; name: string };
export type Settlement = { number: number; void?: boolean; rows: (Seat & { delta: number; balance: number | null })[] };
export type FlowerTableView = {
  players: { status: string; bet: number; cards: Card[] | null }[];
  pot: number; dealer: number; turn: number; round: number; current_bet: number;
  legal: { look?: boolean; fold?: boolean; call?: number; raises?: number[]; compare?: number[] };
};
export type RoomView = RoomSummary & {
  seats: Seat[]; seat: number | null; owner_id: number; version: number; deadline: string | null;
  group_invited: boolean; balance: number; requirement: number; fee_charged: boolean; results: Settlement[]; options: RoomOptions;
  table: sc.ScView | FlowerTableView | null;
};
export type Lobby = {
  balance: number; games: Record<RoomGame, FeeOption>; rooms: RoomSummary[];
  mall_open: boolean; can_manage: boolean;
};
export type GroupRoomSettings = Record<RoomGame, Pick<FeeOption, 'enabled' | 'points'>>;
export type InviteTarget = 'group' | 'private';

async function request<T>(route: string, method: string, body?: object): Promise<T> {
  const result = await fetch('/miniapp/api/rooms' + route, {
    method,
    headers: { Authorization: 'tma ' + initData.raw(), 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await result.json();
  if (!result.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请刷新房间');
  return data;
}

export function roomRequest<T>(id?: number, body?: object) {
  return request<T>(id === undefined ? '' : '/' + id, body ? 'POST' : 'GET', body);
}

export function saveGroupRoomSettings(settings: GroupRoomSettings) {
  return request<GroupRoomSettings>('/settings', 'PUT', settings);
}

export function roomInvite(id: number, target: InviteTarget) {
  return request<{ message_id?: string; sent?: boolean }>('/' + id + '/invite', 'POST', { target });
}
