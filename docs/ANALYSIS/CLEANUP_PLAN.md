# Cleanup Plan

Voorgestelde verwijderingen, gerangschikt op impact. Niets wordt verwijderd
zonder bevestiging van de gebruiker.

## A. SAFE — kan direct weg (junk / regenereerbaar)

| Pad | Grootte | Reden |
|---|---:|---|
| `logs/bot_log.txt.rotation.log` | **5.099 MB** | Rotation-log van rotation-log; pure ruis |
| `logs/bot_log.txt.5` | 5,9 MB | Oude rotated log (kan weg of gecomprimeerd) |
| `logs/bot_log.txt.1` | 2,05 MB | idem |
| `logs/pairs_arbitrage.jsonl` | 6,07 MB | Stale (laatste write 2026-02-13) |
| `_diag_out.txt` (root) | 13 KB | Eenmalige diagnose-output |
| `_diag_btceth.py` (root) | 0,5 KB | Ad-hoc debug script |
| `_align_enj.py` (root) | 1,2 KB | Ad-hoc fix-script |
| `_backtest_atr_trailing.py` (root) | 14 KB | Hoort in `backtest/experiments/`, niet root |
| `testout.txt` (root) | 0,5 KB | Test stdout dump |
| `param_log.txt` (root) | 14 KB | Onduidelijke output (geen referenties in code?) |
| `start_bot.log` (root) | 26 KB | Hoort in `logs/` |
| `start_automated.ps1.old` (root) | 3,7 KB | Oude versie, in git history |
| `scripts/_check_doge_dca.py` | 1,4 KB | One-shot DCA-check (issue al gefixt) |
| `scripts/_check_sol.py` | 3,1 KB | idem |
| `scripts/_deep_log_search.py` | 3,1 KB | Ad-hoc grep-script |
| `scripts/_find_orders.py` | 2,6 KB | Ad-hoc |
| `scripts/_find_sol.py` | 1,8 KB | Ad-hoc |
| `scripts/_patch_doge_dca.py` | 3,3 KB | One-shot patch (al toegepast) |
| `scripts/_recent_trades.py` | 1,5 KB | Ad-hoc |
| `scripts/_send_update.py` | 2,1 KB | One-shot Telegram-broadcast |

**Totaal vrij te maken: ~5,1 GB** (overheersend de rotation log).

## B. NEEDS REVIEW — backups (274 mappen, 0,7 MB totaal)

`backups/` bevat 274 subdirs van 2026-03-09 t/m 2026-04-30. Totale grootte
slechts 0,7 MB (kleine state-snapshots), dus geen schijfruimteprobleem, maar
maakt `Get-ChildItem` traag en cluttered.

**Voorstel**: behoud laatste 14 dagen (~30–40 mappen), verwijder oudere.
Of: zip oude per maand (`backups/2026-03.zip`).

## C. DOCS-cleanup (geen verwijdering, alleen archiveren)

Verplaats naar `docs/archive/`:
- `claude_opus_analysis_prompt.md`
- `claude_opus_dca_redesign_prompt.md`
- `claude_opus_deep_profit_prompt.md`
- `claude_opus_full_bug_analysis_prompt.md`
- `BUG_ANALYSIS_2026-03-27.md`
- `FINDINGS_AND_FIXES.md` (eenmalig assessment)

## D. DUBIEUS — nader onderzoek nodig (NIET nu verwijderen)

| Pad | Reden |
|---|---|
| `modules/trading_sync.py` | Mogelijk te dedupliceren met `bot/sync_engine.py` (zie repo memory) — eerst migratiepad bouwen |
| `tools/dashboard/` | Mogelijk vervangen door `tools/dashboard_v2/`, maar verifieer eerst |
| `notifier.py` (root) | Wordt het nog gebruikt? Zo niet → `tools/` of weg |
| `utils.py` (root) | Generieke helpers vs `bot/helpers.py` — kandidaat voor consolidatie |
| `setup.py` | Project gebruikt requirements + Dockerfile; mogelijk overbodig naast `pyproject.toml` (afwezig?) |

## E. .gitignore aanvullen

Voeg toe (om herhaling te voorkomen):
```
logs/*.rotation.log
logs/*.jsonl
_*.py
_diag_*
testout.txt
param_log.txt
start_bot.log
*.old
trade_features.csv
```

## Voorgestelde uitvoering

1. **Stap 1 — Sectie A volledig verwijderen** (na bevestiging)
2. **Stap 2 — Sectie B**: oude backups > 30 dagen archiveren naar één zip
3. **Stap 3 — Sectie C**: `docs/archive/` aanmaken en bestanden verplaatsen
4. **Stap 4 — `.gitignore` aanvullen** + commit

Geschatte vrijgemaakte ruimte: **~5,1 GB**.
