# polymarket-weather-bot (dry-run first)

This is a small runner for the Simmer SDK API to scan weather-tagged markets and (optionally) simulate trades using `dry_run: true`.

## Safety
- **Default mode is dry-run.**
- Never write the Simmer API key to disk.
- Use 1Password secret references via `op run`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (dry-run scan)

The Simmer API key is stored in 1Password item `Simmer API Key`.

```bash
SIMMER_API_KEY=op://SterlingArcherVault/"Simmer API Key"/password \
  op run -- python -m bot.scan_weather --limit 30
```

## Notes
- Simmer SDK docs: https://simmer.markets/docs.md
