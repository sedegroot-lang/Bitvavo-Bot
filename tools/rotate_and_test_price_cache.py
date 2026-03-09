import sys
from pathlib import Path
import time

# Ensure repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.logging_utils import log
from modules.json_compat import write_json_compat

tiny = Path('data') / 'price_cache.tinydb.json'
if tiny.exists():
    try:
        ts = int(time.time())
        dest = tiny.with_name(f"{tiny.name}.corrupt.{ts}")
        tiny.replace(dest)
        print('ROTATED', dest)
    except Exception as e:
        print('ROTATE_FAILED', e)
        raise SystemExit(2)
else:
    print('NO_TINYDB_FILE')

# Now run the smoke test write
try:
    write_json_compat('price_cache.json', {'__AUTOTEST__-EUR': {'price': 0.456, 'ts': time.time()}}, indent=2)
    print('WROTE price_cache.json via write_json_compat')
except Exception as e:
    print('WRITE_FAILED', e)
    raise SystemExit(3)

# Read tinydb
try:
    with open('data/price_cache.tinydb.json', 'r', encoding='utf-8') as fh:
        preview = fh.read(1200)
    print('--- tinydb preview ---')
    print(preview)
    print('--- end preview ---')
except Exception as e:
    print('READ_TINY_FAILED', e)
    raise SystemExit(4)

print('DONE')
