# Personal Finance App

A single-user Windows desktop app — Electron + React + Express + SQLite — covering five
areas of personal finance:

| Tab | What it does |
|---|---|
| **Everyday** | Day-to-day money in and out, running net, savings rate, highest spending |
| **Spending** | Monthly category breakdown of outflows |
| **LenDen** | P2P lending ledger — payouts, reinvestments, returns by period, projection |
| **Loan** | Loan against mutual funds — comparator, calculator, payoff schedules |
| **Mutual Funds** | Holdings valued on NAV, with the share funded by LenDen returns |
| **Analytics** | Local usage log — which features get used, and which never do |

Everything runs locally: no network calls, no account, no telemetry. The app is PIN-locked
and the local API requires the session token, so the lock is not merely cosmetic.

Everyday and Spending read one shared ledger rather than duplicating entries — money out
logged on Everyday appears in Spending's category breakdown automatically.

## The LenDen model

LenDen returns money at irregular intervals as an undifferentiated mix of principal and
interest, so this tracks **overall portfolio flow**, not individual loans.

## Running it

Electron hosts the Express server in-process on a random loopback port, so there is no
terminal, no fixed port, and nothing to start by hand.

```bash
npm install
npm run dist      # builds the Windows installer into release/
```

Run that installer once; after that it's a Start-menu / desktop icon like any other app.

| script | what it does |
|---|---|
| `npm run app` | run the desktop app from source (no packaging) |
| `npm run dist` | build the Windows installer into `release/` |
| `npm run dev` | browser dev mode with live reload (Vite on 5173, API on 4000) |
| `npm start` | headless server only, browser at http://localhost:4000 |
| `npm run app:rebuild` | rebuild `better-sqlite3` against Electron's ABI |

### Where your data lives

`%APPDATA%\lenden-portfolio-tracker\lenden.db` — outside the install folder, so
reinstalling or updating the app never touches it. **File → Show data folder** opens it.
On first launch the app copies in an existing `backend/data/lenden.db` if it finds one.

Back it up with that file, or with Export CSV.

### Notes for future maintenance

- `better-sqlite3` is a native module and must match Electron's ABI — after changing the
  Electron version, run `npm run app:rebuild`.
- Runtime deps (`express`, `cors`, `better-sqlite3`) are declared in the **root**
  `package.json` as well as `backend/`. That is deliberate: electron-builder resolves the
  dependency tree from the packaged app's own manifest, and with npm workspaces hoisting
  everything to the root, omitting them there ships an app with an empty `node_modules`.
- `asar` is disabled because the backend is loaded via ESM `import()`, which does not read
  from inside an asar archive.

## Data model

One flat table, no linking between records:

| column | notes |
|---|---|
| `id` | autoincrement |
| `date` | `YYYY-MM-DD` |
| `type` | `deposit` · `payout` · `reinvest` · `withdrawal` |
| `amount` | > 0 |
| `principal_portion` | payouts only, else `NULL` |
| `interest_portion` | payouts only, else `NULL` |

`reinvest` and `withdrawal` are independent entries — they are never tied to a specific
payout. A payout can be split across several later reinvestments/withdrawals or left idle.
The split validation (`principal + interest = amount`, ±0.01) is enforced in the form, the
API, and a table CHECK constraint.

## Metrics

```
portfolio value = deposited + interest earned − withdrawn
deployed        = deposits + reinvested − principal received
idle            = total paid back − reinvested − withdrawn
```

**`idle` counts the whole payout, not just principal.** Interest is spendable cash and in
practice gets reinvested alongside principal, so counting principal alone made `idle` go
negative on every ordinary cycle and fired a false "inconsistent ledger" warning. With the
current definition `deployed + idle == portfolio value` always holds, which makes a
negative `idle` a genuine error signal: a missing payout, or a reinvest/withdrawal entered
higher than the cash actually available. It is never rendered negative in the UI.

**Platform fee:** LenDen deducts its fee before crediting, so the interest figure on a
statement is already net. Enter it as shown — there is no separate fee field, and
`principal + interest = amount` holds.

**Reinvestment is not a deposit.** Only money crossing between the bank and LenDen counts
as `deposit`/`withdrawal`; those are the XIRR cash flows. A `reinvest` moves money from
idle to deployed and is deliberately excluded from XIRR — counting it would inflate the
return badly. If you reinvest a payout and add fresh salary money on the same day, that is
two entries, not one.

**XIRR** is solved with Newton-Raphson (bisection fallback when the tangent leaves the
valid domain), on a 365-day basis, over: deposits as negative flows, withdrawals as
positive flows, and current portfolio value as a final positive flow today. Verified
against Excel's XIRR reference case (0.3733625). Results beyond ±999% are suppressed —
they mean the history is too short to annualise, not that the return is real.

## API

| method | route | notes |
|---|---|---|
| GET | `/api/transactions?sort=&dir=` | sort on `date`, `type`, `amount`, `id` |
| POST | `/api/transactions` | |
| PUT | `/api/transactions/:id` | |
| DELETE | `/api/transactions/:id` | |
| GET | `/api/summary` | totals, allocation, XIRR, warnings, growth series |
| GET | `/api/export` | CSV download |
| POST | `/api/import` | `{ csv, mode: 'append' \| 'replace' }` |

CSV import validates every row first and imports nothing if any row fails, reporting the
offending line numbers. The `id` column in an export is ignored on import.
