# Dota 2 Match Win Predictor

First iteration: a narrow OpenDota public match parser.

## Parser

Install dependencies with `uv`:

```bash
uv sync --dev
```

Collect raw OpenDota `/publicMatches` rows:

```bash
uv run dota-parser collect-public --limit 100
```

Normalize existing raw rows into partitioned Parquet:

```bash
uv run dota-parser normalize-public
```

Run both steps:

```bash
uv run dota-parser parse-public --limit 100
```

The parser stores immutable raw envelopes under `data/raw/opendota/public_matches`,
normalized matches under `data/normalized/matches`, checkpoints under `artifacts/checkpoints`,
and quality issues under `artifacts/quality`.

Patch boundaries are data, not code. Replace the bootstrap interval in `configs/patches.yaml`
with verified Dota 2 patch dates before using the output for training.
