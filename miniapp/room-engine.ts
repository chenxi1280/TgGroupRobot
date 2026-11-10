import { Rng, sc, sichuan } from './room-preview/deskpark/engine';

type Request = {
  op: 'start' | 'move' | 'timeout' | 'next';
  state: sc.ScState;
  names: string[];
  rounds: number;
  seed: number;
  seat: number;
  action: sc.ScAction;
};

function move(state: sc.ScState, seat: number, action: sc.ScAction) {
  const error = sichuan.validate(state, seat, action);
  if (error) throw new Error(error);
  return sichuan.apply(state, seat, action);
}

function run(input: Request) {
  let state = input.state;
  switch (input.op) {
    case 'start':
      state = sichuan.setup({
        players: input.names.map((name) => ({ name, isBot: false })),
        options: { ...sichuan.defaultOptions, rounds: input.rounds },
        seed: input.seed,
      });
      break;
    case 'move':
      state = move(state, input.seat, input.action);
      break;
    case 'timeout':
      for (const seat of sichuan.activeSeats(state)) {
        const action = sichuan.bot(sichuan.view(state, seat), seat, new Rng(input.seed + seat));
        state = move(state, seat, action);
      }
      break;
    case 'next':
      for (const seat of sichuan.activeSeats(state)) state = move(state, seat, { type: 'ready' });
      break;
  }
  return { state, views: state.players.map((_, seat) => sichuan.view(state, seat)) };
}

try {
  let raw = '';
  for await (const part of process.stdin) raw += part;
  console.log(JSON.stringify(run(JSON.parse(raw))));
} catch (error) {
  console.log(JSON.stringify({ error: (error as Error).message }));
}
