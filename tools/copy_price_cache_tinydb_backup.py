import shutil
from pathlib import Path
import time

src = Path('data') / 'price_cache.tinydb.json'
if not src.exists():
    print('SOURCE_NOT_FOUND')
    raise SystemExit(1)
try:
    ts = int(time.time())
    dest = src.with_name(f"{src.name}.corrupt.{ts}")
    shutil.copy2(src, dest)
    print('COPIED', dest)
except Exception as e:
    print('COPY_FAILED', e)
    raise
