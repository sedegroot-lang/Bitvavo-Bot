with open('trailing_bot.py', encoding='utf-8') as f:
    lines = f.readlines()
terms = ['TRAILING_STOP_PCT', 'PARTIAL_TP_1', 'PARTIAL_TP_2', 'PARTIAL_TP_3', 'BUDGET_EUR', 'GRID_BUDGET', 'GRID_ENABLED', 'RSI_ENTRY']
for i, line in enumerate(lines):
    for t in terms:
        if t in line and i < 2000:
            print(f'L{i+1}: {line.rstrip()[:130]}')
            break
