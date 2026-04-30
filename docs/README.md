# Documentatie Index

Welkom bij de docs van de Bitvavo Trading Bot.

## Lezen voor je begint

| Doc | Inhoud |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level architectuur en dataflow |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Hoe de bot draait (Docker, scripts, processen) |
| [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) | Alle config-keys uitgelegd |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Veelvoorkomende problemen |
| [VSCODE_COPILOT_HANDLEIDING.md](VSCODE_COPILOT_HANDLEIDING.md) | Werken met Copilot in deze repo |

## Strategie & roadmap

| Doc | Inhoud |
|---|---|
| [PORTFOLIO_ROADMAP_V2.md](PORTFOLIO_ROADMAP_V2.md) | Actieve fasenroadmap (single source of truth) |
| [STRATEGY_IDEAS_COMPLETE.md](STRATEGY_IDEAS_COMPLETE.md) | Strategiekatalogus en ideeën |
| [SIGNAL_CONFIDENCE_RESEARCH.md](SIGNAL_CONFIDENCE_RESEARCH.md) | Onderzoek naar conformal / signal confidence |
| [advanced_features.md](advanced_features.md) | Beschrijving van geavanceerde features |
| [COPILOT_ROAD_TO_10.md](COPILOT_ROAD_TO_10.md) | Plan om naar score 10 te groeien |
| [TRAILING_MONOLIET_PLAN.md](TRAILING_MONOLIET_PLAN.md) | Plan voor afbouw van `trailing_bot.py` monoliet |

## Operatie

| Doc | Inhoud |
|---|---|
| [FIX_LOG.md](FIX_LOG.md) | **Verplicht lezen vóór elke bugfix** — historiek van alle fixes |
| [DASHBOARD_V2.md](DASHBOARD_V2.md) | Dashboard V2 (FastAPI + PWA, port 5002) |
| [DASHBOARD_V2_TUNNEL.md](DASHBOARD_V2_TUNNEL.md) | Externe toegang via tunnel |

## Analyse

| Map | Inhoud |
|---|---|
| [ANALYSIS/](ANALYSIS/README.md) | Codebase-analyse 2026-04-30: scorecard, component-detail, cleanup-plan, backlog |
| [archive/](archive/README.md) | Eenmalige LLM-prompts en superseded strategy-docs |
| [grafana/](grafana/) | Grafana dashboard JSONs (te importeren) |

## Conventies

Zie `.github/copilot-instructions.md` (workspace root) voor de codeconventies,
config-locaties en imports/test-patronen.
