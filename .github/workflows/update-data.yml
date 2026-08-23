name: Aggiorna dati calcio

on:
  schedule:
    - cron: '0 6,23 * * *'
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'scripts/**'
      - '.github/workflows/**'

permissions:
  contents: write

concurrency:
  group: aggiorna-dati
  cancel-in-progress: false

jobs:
  aggiorna:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout del repository
        uses: actions/checkout@v4

      - name: Configura Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Recupera i dati da API-Football
        env:
          API_FOOTBALL_KEY: ${{ secrets.API_FOOTBALL_KEY }}
          MAX_CHIAMATE: '90'
          MAX_DETTAGLIO: '3'
        run: python scripts/fetch_data.py

      - name: Committa il JSON aggiornato
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add docs/data.json
          if git diff --staged --quiet; then
            echo "Nessuna variazione nei dati, niente da committare."
          else
            git commit -m "Aggiornamento dati $(date -u '+%Y-%m-%d %H:%M UTC')"
            git push
          fi
