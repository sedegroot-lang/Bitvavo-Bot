# 🎯 Road to 10/10 — Plan voor Copilot

> **Status:** Living document. Bot zit nu op **7.0/10** (review 2026-04-27).  
> **Doel:** **10/10** = onderhoudbaar, voorspelbaar, deelbaar, en ML-volwassen.  
> **Eigenaar van dit plan:** Copilot zelf — gebruikt als checklist tijdens elke sessie.

---

## 📊 Huidige cijfers per gebied (baseline)

| Gebied | Nu | Doel | Gap |
|---|---|---|---|
| Trading-resultaat | 7.5 | 9.0 | +1.5 |
| Code-architectuur | 6.5 | 9.5 | +3.0 |
| Testdekking | 8.0 | 9.5 | +1.5 |
| Observability/dashboard | 6.5 | 9.0 | +2.5 |
| Documentatie | 8.5 | 9.5 | +1.0 |
| Repo-hygiëne | 4.0 | 9.5 | +5.5 |
| ML-volwassenheid | 6.0 | 8.5 | +2.5 |
| Deelbaarheid (anderen kunnen het runnen) | 5.5 | 9.0 | +3.5 |

---

## 🛠️ Werkpakket (geprioriteerd)

### Fase 1 — Repo-hygiëne (snelle winst, 4-5/10 → 9/10)

- [ ] **Verplaats alle `_*.py` debug-scripts (45+) naar `scripts/debug/`** — gitignore eventueel oude.
- [ ] **Verplaats `_*.txt`/`_*.json` analyse-output naar `tmp/`** of `.gitignore`.
- [ ] **`requirements.txt` opsplitsen** in `requirements-core.txt` + `requirements-ml.txt` + `requirements-dev.txt` (optioneel torch/xgboost).
- [ ] **`.editorconfig` toevoegen** (line-endings + indent consistency).
- [ ] **`Makefile` of `tasks.json`** met standaard commando's: `make test`, `make lint`, `make run`, `make backtest`.
- [ ] **Verifieer `.gitignore`** — geen `.env`, geen logs, geen state-files in git.

### Fase 2 — Monoliet opsplitsen (`trailing_bot.py` 4911 regels → ~500)

- [ ] Identificeer alle nog niet-geëxtraheerde verantwoordelijkheden (loop, scheduler, signal-orchestrator, partial-TP, DCA-trigger, regime-switch).
- [ ] Maak `bot/main_loop.py` (de echte run-loop, dunne wrapper).
- [ ] Maak `bot/scheduler.py` (alle background threads/scheduled jobs).
- [ ] Maak `bot/entry_pipeline.py` (signal scan → score → entry beslissing).
- [ ] Maak `bot/exit_pipeline.py` (trailing/partial-TP/no-loss/sync).
- [ ] `trailing_bot.py` wordt entrypoint van max 300 regels.
- [ ] **Voor elke extractie:** schrijf integratie-test eerst, dan refactor.

### Fase 3 — Observability (6.5 → 9.0)

- [ ] Eén dashboard (kies `dashboard_flask` óf `dashboard_v2`, niet beide).
- [ ] **Structured logging (JSON-lines)** in `logs/events.jsonl` — eenvoudig filterbaar.
- [ ] **Prometheus exporter** op `:9100/metrics` (open_trades, equity, win_rate, slippage_pct).
- [ ] **Grafana dashboard JSON** in `docs/grafana/`.
- [ ] **Telegram daily report** met: equity, P/L, # trades, win rate, top/bottom market, missed signals (zoals UNI).

### Fase 4 — ML-volwassenheid (6.0 → 8.5)

- [ ] **Walk-forward backtest** raamwerk in `backtest/` (geen meer ad-hoc `_backtest_*.py`).
- [ ] **Feature store** — verplaats feature-engineering naar `ai/features/` met versionering.
- [ ] **Model registry** — `models/` krijgt versie + metadata (date, n_train, val_metric).
- [ ] **MAPIE conformal predictions** (al geïnstalleerd) — gebruik voor entry-confidence intervals.
- [ ] **Shadow trading** — alle model-output 1 week shadow loggen voordat live.
- [ ] **Feature drift monitor** — alert als feature distribution >3σ afwijkt van train set.

### Fase 5 — Trading-strategie (7.5 → 9.0)

- [ ] **Limit-orders i.p.v. market** — recapture de 39% slippage.
- [ ] **WebSocket prijs-feed** — sneller dan 25s polling (zie UNI-incident).
- [ ] **DCA opnieuw evalueren** — uitschakelen of strikter (alleen sterk score >12).
- [ ] **Per-market parameters** — top performers (BTC/ETH/SOL) krijgen eigen trailing-config.
- [ ] **Regime-aware entry** — entries blokkeren in `BEARISH` regime tenzij oversold.

### Fase 6 — Deelbaarheid (5.5 → 9.0)

- [ ] **Docker-image die werkt zonder OneDrive paths.** Configureerbare `BOT_ROOT` env var.
- [ ] **`docker compose up`** = bot + dashboard + ML retrain scheduler in één commando.
- [ ] **`SETUP.md`** — stap-voor-stap onboarding voor nieuwe gebruiker (15 min).
- [ ] **Demo-mode** — bot draait met fake API key + replay candles voor tests.
- [ ] **CI/CD compleet** — `release.yml` bouwt Docker image, pusht naar ghcr.io.

### Fase 7 — Veiligheid & robuustheid

- [ ] **Secrets via env**, nooit in `.json` (geen API-keys in OneDrive!).
- [ ] **`bandit` schoon** — alle warnings opgelost.
- [ ] **Kill-switch endpoint** op dashboard (graceful shutdown van bot).
- [ ] **Healthcheck** voor `docker compose` en `systemd`.
- [ ] **Rate-limit metrics** zichtbaar — alert bij >80% van quota.

---

## 🤖 Externe tools die ons helpen — onderzoek

### Multi-agent / coding orchestrators (relevant voor jouw vraag "subagents die analyseren + uitvoeren")

| Repo | Wat doet het | Relevantie voor ons | Sterren | Aanbeveling |
|---|---|---|---|---|
| **[crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)** | Multi-agent: rollen (researcher/coder/reviewer) werken samen aan taken | ⭐⭐⭐⭐⭐ — exact wat jij beschreef ("één analyseert, één voert uit") | ~25k | **Voor analyse-pipelines** (markt scannen → strategie-voorstel → backtest → review) |
| **[ag2ai/ag2](https://github.com/ag2ai/ag2)** (was AutoGen) | Microsoft's multi-agent framework, conversation-based | ⭐⭐⭐⭐ | ~30k | Alternatief voor CrewAI; sterker in code-gen, zwakker in workflows |
| **[All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands)** (was OpenDevin) | Volledig autonome dev-agent: leest code, schrijft, runt tests | ⭐⭐⭐⭐⭐ | ~40k | Kan zelfstandig de Fase 1-2 refactor uitvoeren, met ons als reviewer |
| **[ruvnet/claude-flow](https://github.com/ruvnet/claude-flow)** | Orchestratie van Claude Code subagents (planner/coder/tester) | ⭐⭐⭐⭐⭐ | ~10k | **Past perfect bij onze setup** (we gebruiken al Copilot/Claude) |
| **[Aider-AI/aider](https://github.com/paul-gauthier/aider)** | CLI pair-programmer met git-aware diffs | ⭐⭐⭐⭐ | ~25k | Goed voor refactor-werk; maakt clean diffs |
| **[MervinPraison/PraisonAI](https://github.com/MervinPraison/PraisonAI)** | Low-code multi-agent framework | ⭐⭐⭐ | ~5k | Voor wie geen code wil schrijven; te low-code voor ons |
| **[langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)** | State-machine orchestrator voor LLM-agents | ⭐⭐⭐⭐ | ~10k | Voor de **bot-AI-supervisor** (regime detector → strategy switcher → executor) |

**Mijn aanbeveling:**
1. **`claude-flow`** voor dev-werk — analyzer-agent leest code, planner maakt todos, coder voert uit, tester valideert. Past 1-op-1 op wat je vroeg.
2. **`CrewAI`** of **`langgraph`** *binnen de bot* voor de AI-supervisor → vervangt de huidige `ai_supervisor.py` (1504 regels) met een nette agent-graph.
3. **`OpenHands`** als experiment voor de monoliet-refactor (Fase 2).

### Trading-specifiek

| Repo | Wat we kunnen jatten/leren | Sterren |
|---|---|---|
| **[freqtrade/freqtrade](https://github.com/freqtrade/freqtrade)** | Hyperopt, backtest engine, strategy interface, FreqUI dashboard | ~30k |
| **[hummingbot/hummingbot](https://github.com/hummingbot/hummingbot)** | Connector-architectuur (exchange-agnostisch), market-making strategies | ~9k |
| **[jesse-ai/jesse](https://github.com/jesse-ai/jesse)** | Schone strategy-API, walk-forward optimization, Jupyter integratie | ~6k |
| **[Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot)** | Plugin-architectuur, web-dashboard, tentacles-systeem | ~4k |
| **[microsoft/qlib](https://github.com/microsoft/qlib)** | Production-grade ML voor trading: feature engineering, model zoo | ~16k |
| **[stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading)** | Boek-repo met 200+ notebooks; ML-recipes | ~14k |

**Aanbevelingen voor adoptie:**
- **Freqtrade's `Strategy` interface** kopiëren — abstracte basis-klasse met `populate_buy_trend / populate_sell_trend`. Maakt nieuwe strategieën trivial.
- **Freqtrade's `Hyperopt`** — Bayesian optimization voor onze trailing/score parameters.
- **Qlib's feature pipeline** — vervangt onze ad-hoc feature-extractie.

### Dev-tooling

| Tool | Waarom |
|---|---|
| **`ruff`** | Vervangt Black + isort + flake8 in één tool, 100x sneller |
| **`uv`** | Vervangt pip + virtualenv, 50x sneller (Astral) |
| **`pytest-xdist`** | Tests parallel — bij 30+ test-files merkbaar sneller |
| **`hypothesis`** | Property-based tests voor cost-basis/sync logica |
| **`pre-commit`** (al ingesteld) | Activeren in CI verplicht maken |

---

## 📅 Voorgestelde volgorde (sprints van 1 sessie)

1. **Sprint A (1u):** Fase 1 — repo opruimen. Hoogste ROI.
2. **Sprint B (2u):** Fase 6 — `SETUP.md` + Docker werkend zonder OneDrive. Maakt deelbaar.
3. **Sprint C (3u):** Fase 2 — extract `bot/main_loop.py` + `bot/scheduler.py` uit monoliet (incrementeel, met tests).
4. **Sprint D (1u):** Fase 5 — limit-orders + WebSocket prijs-feed onderzoek.
5. **Sprint E (2u):** Fase 4 — walk-forward backtester opzetten.
6. **Sprint F (1u):** Probeer `claude-flow` of `CrewAI` als externe agent-runner voor analyse-taken.

---

## ✅ Definition of Done = 10/10

- `trailing_bot.py` ≤ 300 regels, alles in pakketten.
- 0 `_*.py` scripts in root.
- `pytest` < 30s, > 90% coverage op kritieke paden.
- `docker compose up` werkt op een vreemde laptop in <15 min.
- Daily Telegram report met alle key-metrics.
- Walk-forward backtest geautomatiseerd, weekly retrain.
- Externe gebruiker kan binnen 1 uur zelf bot draaien zonder hulp.
- Sharpe ratio over rolling 90d > 2.0 (nu onbekend, eerst meten).
- Geen FIX_LOG-entry over `cost_basis`/`sync` in laatste 30d (= robuust).

---

## 📝 Versielog

| Datum | Wijziging | Door |
|---|---|---|
| 2026-04-28 | Initiële versie | Copilot |
