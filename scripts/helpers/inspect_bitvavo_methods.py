from dotenv import load_dotenv
import os
from modules.bitvavo_client import get_bitvavo
load_dotenv()
bitvavo = get_bitvavo()
if not bitvavo:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys).')
    raise SystemExit(1)
attrs = dir(bitvavo)
matches = [a for a in attrs if 'order' in a.lower() or 'cancel' in a.lower()]
print('Candidate methods containing "order" or "cancel":')
for m in matches:
    print(' -', m)
