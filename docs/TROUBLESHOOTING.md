# Troubleshooting Guide

Common issues and solutions for the Bitvavo Trading Bot.

## 🚨 Bot Won't Start

### Problem: "Another instance is already running"
**Cause:** PID file exists from crashed process.

**Solution:**
```powershell
# Remove stale PID files
Remove-Item -Path "data\*.pid" -Force
Remove-Item -Path "locks\*.lock" -Force

# Restart bot
python scripts\startup\start_bot.py
```

### Problem: Import errors
**Cause:** Missing dependencies or wrong Python environment.

**Solution:**
```powershell
# Activate virtual environment
.\.venv\Scripts\Activate

# Install dependencies
pip install -r config\requirements.txt
```

### Problem: API authentication failed
**Cause:** Missing or invalid API credentials.

**Solution:**
1. Check `.env` file exists in project root
2. Verify API key and secret:
```env
BITVAVO_API_KEY=your_key_here
BITVAVO_API_SECRET=your_secret_here
```
3. Ensure no extra whitespace in credentials

---

## 📊 Dashboard Issues

### Problem: Dashboard won't load
**Cause:** Port conflict or Streamlit not installed.

**Solution:**
```powershell
# Check if port 8501 is in use
netstat -an | Select-String ":8501"

# Kill conflicting process
Stop-Process -Id <PID> -Force

# Restart dashboard
.\.venv\Scripts\streamlit run tools\dashboard\dashboard_streamlit.py
```

### Problem: Dashboard is slow
**Cause:** Too many API calls or large data files.

**Solution:**
1. Check `DASHBOARD_AUTOREFRESH_SECONDS` (increase to 120+)
2. Enable lazy loading for Trade Eligibility panel
3. Check `data/trade_log.json` size - archive old trades if > 10MB

### Problem: "No data to display"
**Cause:** Empty trade log or heartbeat file.

**Solution:**
```powershell
# Check if files exist
Test-Path data\trade_log.json
Test-Path data\heartbeat.json

# If missing, create empty trade log
'{"open_trades":{},"closed_trades":[]}' | Out-File -FilePath data\trade_log.json -Encoding utf8
```

---

## 💹 Trading Issues

### Problem: No trades being executed
**Causes & Solutions:**

1. **Score too high**
   - Check `MIN_SCORE_TO_BUY` in config (default: 10)
   - Lower to 5-8 for more trades

2. **RSI out of range**
   - Check `RSI_MIN_BUY` (30) and `RSI_MAX_BUY` (45)
   - Markets might be overbought

3. **Spread too wide**
   - Check `MAX_SPREAD_PCT` (0.4%)
   - Low liquidity markets rejected

4. **Risk limits reached**
   - Check `RISK_SEGMENT_BASE_LIMITS`
   - Check `MAX_OPEN_TRADES`

5. **Balance too low**
   - Check `MIN_BALANCE_EUR`
   - Need at least `BASE_AMOUNT_EUR` available

**Debug:**
```powershell
# Check recent logs
Get-Content logs\bot_log.txt -Tail 100 | Select-String "SKIP|REJECT|risk"
```

### Problem: Trades closing too early
**Cause:** Trailing stop too tight.

**Solution:**
1. Increase `DEFAULT_TRAILING` (e.g., 0.05 → 0.07)
2. Increase `TRAILING_ACTIVATION_PCT` (e.g., 0.017 → 0.025)

### Problem: Trades closing at loss
**Cause:** Stop loss triggered or market reversed.

**Solution:**
1. Check hard stop loss settings:
   - `HARD_SL_ALT_PCT` (4%)
   - `HARD_SL_BTCETH_PCT` (3.5%)
2. Enable DCA to average down: `DCA_ENABLED: true`
3. Review `logs/bot_log.txt` for exit reason

### Problem: DCA not working
**Cause:** RSI too high or DCA limit reached.

**Solution:**
1. Check `RSI_DCA_THRESHOLD` (max 62)
2. Check `DCA_MAX_BUYS` (max 3)
3. Check `DCA_DROP_PCT` (needs 6% drop)

---

## 🤖 AI Issues

### Problem: AI not making suggestions
**Cause:** Insufficient data or disabled.

**Solution:**
```powershell
# Check AI settings
Get-Content config\bot_config.json | Select-String "AI_"

# Ensure enabled
# AI_AUTO_APPLY: true
# AI_REGIME_RECOMMENDATIONS: true
```

### Problem: AI suggestions not applying
**Cause:** Cooldown or invalid parameters.

**Solution:**
1. Check `AI_APPLY_COOLDOWN_MIN` (45 min default)
2. Check `AI_ALLOW_PARAMS` - only listed params can change
3. Check `data/ai_suggestions.json` for pending suggestions

### Problem: XGBoost model errors
**Cause:** Missing or corrupt model file.

**Solution:**
```powershell
# Check model exists
Test-Path ai\ai_xgb_model.json

# Retrain model
python ai\xgb_auto_train.py
```

---

## 🔄 Sync Issues

### Problem: Positions not syncing with Bitvavo
**Cause:** Sync disabled or API error.

**Solution:**
```powershell
# Force sync
python scripts\helpers\sync_from_bitvavo.py

# Check sync settings
# SYNC_ENABLED: true
# SYNC_INTERVAL_SECONDS: 300
```

### Problem: Balance mismatch
**Cause:** Cached balance or pending orders.

**Solution:**
1. Wait for cache to expire (10s)
2. Check for open orders on Bitvavo
3. Force refresh:
```powershell
python -c "from modules.bitvavo_client import get_client; print(get_client().balance())"
```

---

## 🔔 Notification Issues

### Problem: Telegram not working
**Cause:** Invalid token or chat ID.

**Solution:**
1. Verify bot token with BotFather
2. Get chat ID: send message to bot, check:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Set in config:
   ```json
   "TELEGRAM_ENABLED": true,
   "TELEGRAM_BOT_TOKEN": "123456:ABC...",
   "TELEGRAM_CHAT_ID": "12345678"
   ```

---

## 💾 Data Issues

### Problem: Trade log corrupted
**Cause:** Crash during write.

**Solution:**
```powershell
# Check for backup
Get-ChildItem backups\ -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 5

# Restore from backup
Copy-Item backups\<latest>\trade_log.json data\trade_log.json
```

### Problem: Disk space low
**Cause:** Log files or backups growing.

**Solution:**
```powershell
# Check sizes
Get-ChildItem -Path . -Recurse | 
    Sort-Object Length -Descending | 
    Select-Object -First 10 FullName, @{N="MB";E={[math]::Round($_.Length/1MB,2)}}

# Clean old backups (keep last 10)
Get-ChildItem backups\ | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -Skip 10 | 
    Remove-Item -Recurse -Force

# Clean old logs
Get-ChildItem logs\*.log* | 
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | 
    Remove-Item -Force
```

---

## 🔧 Performance Issues

### Problem: High CPU usage
**Cause:** Too many API calls or tight loop.

**Solution:**
1. Increase `SLEEP_SECONDS` (10 → 15)
2. Reduce `MAX_MARKETS_PER_SCAN` (50 → 30)
3. Enable caching in config

### Problem: High memory usage
**Cause:** Large cache or memory leak.

**Solution:**
1. Check cache settings - LRU cache limits to 1000 items
2. Restart bot periodically
3. Monitor with:
```powershell
Get-Process python | Select-Object Id, WorkingSet64, CPU
```

---

## 🐛 Debug Mode

Enable detailed logging:

```json
{
  "LOG_LEVEL": "DEBUG",
  "SIGNALS_DEBUG_LOGGING": true,
  "RL_LOG_STATES": true
}
```

View real-time logs:
```powershell
Get-Content logs\bot_log.txt -Wait -Tail 50
```

---

## 📞 Getting Help

1. **Check logs:** `logs/bot_log.txt`
2. **Check heartbeat:** `data/heartbeat.json`
3. **Run diagnostics:**
   ```powershell
   python scripts\helpers\check_processes.py
   python scripts\helpers\analyze_bot_deep.py
   ```
4. **Review recent changes:** `git log --oneline -10`

---

## 🔄 Reset & Recovery

### Full Reset (keep config)
```powershell
# Stop bot
Get-Process python | Stop-Process -Force

# Clear runtime data
Remove-Item data\*.json -Force
Remove-Item data\*.pid -Force
Remove-Item locks\* -Force

# Create fresh trade log
'{"open_trades":{},"closed_trades":[]}' | Out-File data\trade_log.json -Encoding utf8

# Restart
python scripts\startup\start_bot.py
```

### Factory Reset (fresh install)
```powershell
# Backup current config
Copy-Item config\bot_config.json config\bot_config.backup.json

# Remove all data
Remove-Item data\* -Force
Remove-Item logs\* -Force
Remove-Item locks\* -Force

# Restore default config or keep backup
```
