import glob, os

files_to_check = [
    'trailing_bot.py',
    'bot/trailing.py',
    'bot/performance.py',
    'modules/trading_dca.py',
    'config/bot_config.json',
]

terms = ['TRAILING_STOP_PCT', 'TRAILING_STOP_ACTIVATION', 'PARTIAL_TP_1', 'PARTIAL_TP_2', 'PARTIAL_TP_3',
         'BUDGET_EUR', 'GRID_BUDGET', 'GRID_ENABLED', 'RSI_ENTRY', 'trailing_stop_pct', 'partial_tp']

for fname in files_to_check:
    if not os.path.exists(fname):
        continue
    with open(fname, encoding='utf-8') as f:
        lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        for t in terms:
            if t.lower() in line.lower() and ('get(' in line or '=' in line or '"' in line):
                if not found:
                    print(f'\n=== {fname} ===')
                    found = True
                print(f'  L{i+1}: {line.rstrip()[:140]}')
                break
