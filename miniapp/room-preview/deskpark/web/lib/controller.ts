import type { sichuan } from '../../engine';

export interface GameController<View, Action> {
  def: typeof sichuan;
  view: View;
  seat: number | null;
  players: { name: string; avatar?: string }[];
  version: number;
  deadlines: Record<number, number>;
  act(action: Action): string | null;
  canRestart: boolean;
  restart(): void;
  leave(): void;
}
