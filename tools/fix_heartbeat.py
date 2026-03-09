#!/usr/bin/env python3
"""
Simple helper to inspect and (safely) fix heartbeat.json if it contains partial/malformed JSON.
- Makes a backup of heartbeat.json before any write.
- Tries to parse the file; if parse fails and file contains multiple JSON objects concatenated, it will extract the last valid JSON object and write that back atomically.
- Prints a short report.
"""
import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
HEARTBEAT = os.path.join(ROOT, 'data', 'heartbeat.json')
BACKUP_DIR = os.path.join(ROOT, 'data', 'backups')

os.makedirs(BACKUP_DIR, exist_ok=True)

def backup(path):
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    dst = os.path.join(BACKUP_DIR, f'heartbeat.json.bak.{ts}')
    shutil.copy2(path, dst)
    #!/usr/bin/env python3
    """
    Simple helper to inspect and (safely) fix heartbeat.json if it contains partial/malformed JSON.
    - Makes a backup of heartbeat.json before any write.
    - Tries to parse the file; if parse fails and file contains multiple JSON objects concatenated, it will extract the last valid JSON object and write that back atomically.
    - Prints a short report.
    """
    import json
    import os
    import shutil
    from datetime import datetime

    ROOT = os.path.dirname(os.path.dirname(__file__))
    HEARTBEAT = os.path.join(ROOT, 'heartbeat.json')
    BACKUP_DIR = os.path.join(ROOT, 'data', 'backups')

    os.makedirs(BACKUP_DIR, exist_ok=True)

    def backup(path):
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        dst = os.path.join(BACKUP_DIR, f'heartbeat.json.bak.{ts}')
        shutil.copy2(path, dst)
        return dst


    def try_load(path):
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        try:
            return json.loads(text), None
        except Exception:
            return None, text


    def extract_last_valid_json(text):
        # heuristic: find last '{' and try to parse forward from there repeatedly
        last_open = text.rfind('{')
        if last_open == -1:
            return None
        candidate = text[last_open:]
        # try simple parse first
        try:
            return json.loads(candidate)
        except Exception:
            # fallback: try to find a substring between balanced braces
            depth = 0
            start = None
            for i, ch in enumerate(text):
                if ch == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start is not None:
                        try:
                            part = text[start:i+1]
                            return json.loads(part)
                        except Exception:
                            start = None
                            continue
            return None


    def atomic_write(path, data_str):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data_str)
        os.replace(tmp, path)


    if __name__ == '__main__':
        if not os.path.exists(HEARTBEAT):
            print('heartbeat.json not found at', HEARTBEAT)
            raise SystemExit(1)

        parsed, raw = try_load(HEARTBEAT)
        if parsed is not None:
            print('heartbeat.json is valid JSON. No action required.')
            print(json.dumps(parsed, indent=2))
            raise SystemExit(0)

        print('heartbeat.json is malformed. Creating backup and attempting repair...')
        bak = backup(HEARTBEAT)
        print('Backup written to', bak)

        fixed = extract_last_valid_json(raw)
        if fixed is None:
            print('Could not extract a valid JSON object from heartbeat.json. Manual inspection needed.')
            raise SystemExit(2)

        fixed_str = json.dumps(fixed, ensure_ascii=False, indent=2)
        atomic_write(HEARTBEAT, fixed_str)
        print('heartbeat.json repaired (last valid JSON object written).')
        print(json.dumps(fixed, indent=2))