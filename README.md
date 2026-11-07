```
██████╗ ██╗   ██╗███████╗██╗  ██╗██████╗  ██████╗ ████████╗
██╔══██╗██║   ██║██╔════╝██║  ██║██╔══██╗██╔═══██╗╚══██╔══╝
██████╔╝██║   ██║███████╗███████║██████╔╝██║   ██║   ██║
██╔══██╗██║   ██║╚════██║██╔══██║██╔══██╗██║   ██║   ██║
██║  ██║╚██████╔╝███████║██║  ██║██████╔╝╚██████╔╝   ██║
╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝  ╚═════╝    ╚═╝
```

**Statlockle Rush solver & humanized bot** for [statlocker.gg](https://statlocker.gg).

Solves every puzzle type in the *Statlockle Rush* survival quiz, answers with human-like
timing so runs survive the server's anti-cheat, and learns from every reveal it sees.

> Top result: **#2 on the Season 2 leaderboard — 64 166 points** (raw runs have hit 87 k-class survival).

---

## What it does

`rushbot` plays a run of Statlockle Rush end-to-end:

1. **Starts** a run and pre-solves all 300 puzzles from public datasets.
2. **Answers** each puzzle with the correct body for its type.
3. **Paces** answers like a human (per-puzzle speed window + jitter + hesitation).
4. **Learns** the true value of every option from the server's `reveal` block, and reuses it
   later — fresh reveals override stale cached datasets. On harvested runs the solver is
   **99.7% accurate**; the only soft spot is `soulsquares` (~82%, limited by sparse map data).
5. **Finishes** the run and reports score, strikes, rank.

### Puzzle types covered

| type | how |
|---|---|
| `pair`, `rank4`, `oddoneout`, `reversepick`, `statpick`, `minimap` | order by the resolved value |
| `overunder` | compare against the line |
| `buckets` | split high/low around the line |
| `estimate` | value snapped to the slider grid (with PP tolerance) |
| `scale` | ratio between reference and target |
| `chain` | **step-by-step** `{step, guess}` — the wire format the server actually accepts |
| `soulsquares` | spatial kNN over learned samples (~82% on unseen pairs; entityId encodes map position) |
| `shopdash`, `iconcost` | found-items + human `pickMs` cadence |
| `kitcheck` | ability-slot order from kit icons |
| `abilityorder` | AP order from the ability-order stats |

### Anti-bot / humanization

The server flags runs whose *answer times look wrong* (`valid: false` → "Run not ranked").
`rushbot` targets the human middle of each puzzle's speed window:

```python
delay = fastMs + (parMs - fastMs) * U(0.35, 0.65) + 1800ms   # + 10% long stares
```

- `--read-speed fast|normal|slow` scales how fast the bot is seen (slow → higher speedMult).
- Chain steps run on the bare countdown (a slow pace blows the whole-chain `parMs`).
- Verification: a fixed play cadence yields `valid: true` in ~10-15% of runs — enough to place
  a high score on the board.

---

## Install

**Windows, one click:** double-click `setup.bat` — it checks Python, installs dependencies and
opens an interactive menu (ASCII UI, no PowerShell needed).

**Manual:**

```bat
python -m pip install -r requirements.txt
python -m rushbot fetch            :: download public datasets
python -m rushbot board            :: current leaderboard
```

Requires **Python 3.10+**. Only external dependency: `cryptography` (cookie decryption on Windows).

---

## Quick start

```bat
:: 1. pull the statlocker session cookie straight from a local browser profile
python -m rushbot brave --browser brave --profile Default

:: 2. solve a saved run payload offline (no network, sanity-check the solver)
python -m rushbot plan start.json

:: 3. play a full run, human-paced
python -m rushbot play --latency --read-speed slow
```

`brave` reads Chromium cookie DBs (Brave / Chrome / Edge) and decrypts them via DPAPI; for a
browser that is currently *open* it falls back to a volume shadow copy.

---

## CLI reference

```
rushbot brave   [--browser brave|chrome|edge] [--profile Default] [--out FILE]
rushbot plan    start.json                 # dry-solve a saved /rush/start payload
rushbot play    [--latency] [--read-speed fast|normal|slow] [--max N] [--delay MS]
rushbot runs    [--runs N] [--latency]
rushbot vigil   [--cookie FILE]            # keep playing until a run finally ranks
rushbot calib   samples.jsonl              # per-family accuracy report
rushbot board                              # season leaderboard top
rushbot fetch                              # refresh cached datasets
rushbot auth    --cookie FILE              # verify a Steam session cookie
```

Key flags:

- `--latency` — human answer pacing (the recommended mode).
- `--read-speed slow` — claim a slow reader: the server permits a larger `solveMult`.
- `--refresh` — re-download public datasets first (they drift).
- `--target N` — stop once the score reaches `N`.

---

## How it works

```
api.py        HTTP client (Cloudflare warm-up, /rush endpoints, cookie jar)
data.py       cached public datasets: heroes, items, abilities, hero/item usage, misc
resolve.py    family -> numeric value per option (the resolver rules)
knowledge.py  learned (family, context, entity) -> true value, harvested from reveals
solve.py      puzzle -> answer body
play.py       run orchestration, pacing, retries, logging
brave.py      Chromium cookie extraction + DPAPI/AES-GCM decryption
calibrate.py  accuracy report over harvested samples
```

- Every value the generator compares comes from a public endpoint; `resolve.py` maps each
  family onto the right field. Where the endpoint is only an approximation, `knowledge.py`
  overrides it once the server reveals the exact number.
- Run logs land in `data/runs/*.jsonl`; they double as training data for `calib`/`seed`.

---

## Results (Season 2)

| # | account | score |
|---|---|---|
| 1 | #мех | 87 071 |
| **2** | **SerByter** | **64 166** |
| 3 | Wormy | 40 411 |
| 4 | IcyRain | 22 497 |

*Disclaimer: account scores/ranks are illustrative and drift as the leaderboard moves. Use at
your own risk — automated play may violate the site's terms; only point this at accounts you own.*
