import json
import time
import sys
from pathlib import Path

# Ensure repo root is on sys.path so 'modules' package can be imported when
# this script is executed directly from tools/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.json_compat import write_json_compat
from modules.logging_utils import log

print('Starting smoke test for price_cache mirror')
try:
    write_json_compat('price_cache.json', {'__AUTOTEST__-EUR': {'price': 0.123, 'ts': time.time()}}, indent=2)
    print('WROTE price_cache.json via write_json_compat')
except Exception as e:
    print('WRITE FAILED:', e)

# Read tinydb file
tiny_path = Path('data') / 'price_cache.tinydb.json'
if tiny_path.exists():
    try:
        with open(tiny_path, 'r', encoding='utf-8') as fh:
            data = fh.read()
        print('--- BEGIN tinydb content preview ---')
        print(data[:1000])
        print('--- END preview ---')
    except Exception as e:
        print('READ tinydb FAILED:', e)
else:
    print('tinydb file not found:', tiny_path)

print('Smoke test finished')
