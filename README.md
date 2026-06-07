# Budget Display

A fullscreen budget-pace dashboard designed to run on a Raspberry Pi connected to a small display. Shows whether you're spending too fast, on track, or have room to spend this month.

## Running locally

```bash
npm install
npm run dev
```

This starts both servers concurrently:

- **Client** — Vite dev server at `http://localhost:5173`
- **Server** — Express API at `http://localhost:3001`

To run them separately:

```bash
npm run dev:client   # Vite frontend only
npm run dev:server   # Express backend only
```

## Project structure

```
budget-display/
├── client/          # React + TypeScript + Vite frontend
│   └── src/
│       ├── App.tsx  # Main display component
│       └── App.css  # All styles (preserves original design)
├── server/          # Express backend
│   └── src/
│       ├── index.ts               # Server entry point
│       ├── routes/budget.ts       # GET /api/budget-status
│       └── services/
│           ├── budgetCalculator.ts  # Calculation logic (edit mock inputs here)
│           └── ynab.ts              # Future YNAB integration stub
└── shared/
    └── types/budget.ts  # Shared BudgetStatus type
```

## Mock data

Mock inputs live in `server/src/routes/budget.ts`:

```ts
const MOCK_INPUT = {
  monthlyBudget: 1800,
  spent: 720,
};
```

The backend calculates `expected`, `difference`, `spentProgress`, `expectedProgress`, and `status` from these values using today's date. To simulate different states, change `spent` here.

## YNAB integration

When ready to connect real data:

1. Add your credentials to `.env` (see `.env.example`)
2. Implement `getYnabBudgetStatus()` in `server/src/services/ynab.ts`
3. Replace the `MOCK_INPUT` call in `server/src/routes/budget.ts` with `await getYnabBudgetStatus()`

The `/api/budget-status` response shape is stable — the frontend won't need changes.

## Running on Raspberry Pi

Eventually this will run in kiosk mode on a Pi connected to a small display:

1. Build the frontend: `npm run build` (outputs to `dist/client/`)
2. Run the Express server in production: `node server/src/index.js` (after `npm run build:server`)
3. Serve `dist/client/` as static files from Express (add a `express.static` route)
4. Launch Chromium in kiosk mode pointing at `http://localhost:3001`

A helper script and systemd service file can be added here when the Pi setup is finalized.
