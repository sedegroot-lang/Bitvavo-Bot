"""Fix corrupted dca_max values in open trades."""
import json

path = 'data/trade_log.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

ot = data.get('open', {})
fixed = 0
for m, t in ot.items():
    dca_max = t.get('dca_max')
    print(f'{m}: dca_max={dca_max}')
    if isinstance(dca_max, (int, float)) and dca_max > 5:
        print(f'  -> FIXING: {dca_max} -> 1')
        t['dca_max'] = 1
        fixed += 1

if fixed > 0:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f'\nFixed {fixed} trades.')
else:
    print('\nNo fixes needed.')
