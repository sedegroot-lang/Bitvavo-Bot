#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from modules.bitvavo_client import get_bitvavo

b = get_bitvavo()
bal = [x for x in b.balance({}) if float(x.get('available',0)) > 0 or float(x.get('inOrder',0)) > 0]
print('=== BITVAVO BALANCES ===')
for x in bal:
    sym = x['symbol']
    avail = float(x['available'])
    in_order = float(x.get('inOrder', 0))
    print(f"{sym}: available={avail:.4f}, inOrder={in_order:.4f}")
