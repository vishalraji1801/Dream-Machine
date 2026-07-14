# Current Process Flow

The system **as wired today** (paper, `router_enabled: true`, scanner top-10).
Diagrams are [Mermaid](https://mermaid.js.org) — they render in VS Code / GitHub,
and Lucidchart imports them via **File → Import → Mermaid**.

## Daily lifecycle + the 5-minute intraday cycle

```mermaid
flowchart TD
    A["bot auth · daily TOTP login"] --> B["Startup · load config + modules<br/>build LiveRouter (router_enabled)"]
    B --> C{"Trading day &<br/>market open?"}
    C -- "No" --> Z["Idle · holiday/weekend/off-hours"]
    C -- "Yes · 09:15" --> D["Subscribe watchlist on WebSocket<br/>build candles from ticks"]
    D --> E(["Every 5-min cycle"])

    E --> F["Manage open positions<br/>trailing SL · SL/target exits"]
    F --> G{"Circuit breakers OK?<br/>daily-loss · drawdown · API errors"}
    G -- "Halted" --> E
    G -- "OK" --> H{"In entry window<br/>& not an event day?"}
    H -- "No" --> E
    H -- "Yes" --> I["Get quotes for the watchlist pool"]

    I --> J["SCANNER · rank by RVOL / momentum / range<br/>➜ TOP 10 stocks"]
    J --> K["ROUTER · index ➜ MarketState<br/>(ADX, ATR%, BB-width)"]
    K --> L["Regime classifier + hysteresis<br/>STRONG_TREND · RANGE · QUIET · CHOP"]
    L --> M["Route · pick strategy + params + weight<br/>for this regime (strategies/*.yaml)"]
    M --> N{"Any active strategy<br/>with a positive edge?"}
    N -- "No (non-trend / no fit)" --> O["TRADE NOTHING this cycle"]
    N -- "Yes · supertrend" --> P["For each of the 10 stocks:<br/>generate signal with the regime's params"]
    P --> Q{"Signal + risk checks pass?<br/>sizing · order-value cap · sector cap · margin"}
    Q -- "No" --> E
    Q -- "Yes" --> R["Place PAPER order<br/>tag (strategy, regime)"]
    R --> S[("Persist to trades.db<br/>routing · signal · trade")]
    O --> S
    S --> E

    E -. "15:15" .-> T["Square off ALL positions (MIS)"]
    T --> U["EOD summary ➜ Telegram"]
```

## Control, monitoring & the learning loops

```mermaid
flowchart LR
    subgraph CTRL["Control & Monitoring"]
        WA["Web App (PWA)<br/>dashboard · controls · settings · backtest"]
        TG["Telegram<br/>start/stop/pause · alerts"]
    end
    subgraph BOT["Trading bot"]
        LOOP(["5-min cycle"])
        LEDGER[("trades.db<br/>tagged mode/regime/run")]
    end
    subgraph LEARN["Offline learning (scheduled)"]
        ANALYST["Weekly analyst<br/>ledger ➜ regime_fit map"]
        TUNE["Auto-tuner<br/>walk-forward ➜ bounded overlay"]
    end

    WA --> LOOP
    TG --> LOOP
    LOOP --> LEDGER
    LEDGER --> ANALYST
    ANALYST -. "updates strategies/*.yaml" .-> LOOP
    LEDGER --> TUNE
    TUNE -. "validated params" .-> LOOP
```

## Legend / current state
- **Scanner** = *where* to look (top-10 stocks). **Router** = *what* to run (strategy+params by regime). Two independent axes.
- **Active today:** only **supertrend** has a seeded/validated edge, so the router runs it in **STRONG_TREND** regimes and **sits out** otherwise.
- **Not yet wired:** the **daily/positional strategies** (donchian, bb) — they showed the stronger 10-yr edge but need a separate daily sleeve. The **regime_fit map** is currently a seed; the weekly analyst replaces it with learned values as the ledger fills.
- **Discipline:** unvalidated params never trade live/paper; premarket sets the risk ceiling, intraday can only lower it; every decision is persisted and auditable.
