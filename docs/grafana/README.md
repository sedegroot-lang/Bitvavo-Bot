# Grafana Dashboard

## Bitvavo Bot Dashboard (`bitvavo_bot_dashboard.json`)

Drop-in dashboard for Grafana 10+. Imports without modification once a Prometheus
data source named "Prometheus" is configured.

### Setup

1. **Prometheus config** — add a scrape job for the Bitvavo bot dashboard V2:

   ```yaml
   scrape_configs:
     - job_name: bitvavo-bot
       scrape_interval: 30s
       metrics_path: /metrics
       static_configs:
         - targets: ['127.0.0.1:5002']
   ```

2. **Grafana** — Dashboards → New → Import → upload `bitvavo_bot_dashboard.json`.

### Panels

| Panel | Metric | What it shows |
|---|---|---|
| Bot Online | `bitvavo_bot_online` | 0/1 heartbeat freshness (<180s) |
| AI Online | `bitvavo_bot_ai_online` | 0/1 AI supervisor heartbeat (<600s) |
| Open Trades | `bitvavo_open_trades` | Currently open positions |
| Account Value | `bitvavo_total_account_value_eur` | Equity (cash + positions) |
| EUR Cash | `bitvavo_eur_cash` | Free EUR balance |
| PnL Timeline | `bitvavo_total_pnl_eur` | Cumulative realised PnL |
| Exposure Timeline | `bitvavo_open_exposure_eur` | EUR tied up in positions |
| Win Rate | `bitvavo_win_rate` | Realised win rate [0..1] |
| Heartbeat Age | `bitvavo_heartbeat_age_seconds` | Seconds since last bot tick |
| Closed Trades Counter | `bitvavo_total_closed_trades` | Lifetime trade count |
| Rate-Limit Usage | `bitvavo_ratelimit_usage_ratio{bucket=...}` | Bitvavo API quota usage per bucket; alert >0.8 |

### Alerts (suggested)

- **Bot down**: `bitvavo_bot_online == 0 for 3m`
- **Heartbeat stale**: `bitvavo_heartbeat_age_seconds > 300`
- **Rate-limit warning**: `max(bitvavo_ratelimit_usage_ratio) > 0.8`
- **PnL drawdown**: `delta(bitvavo_total_pnl_eur[1h]) < -50`
