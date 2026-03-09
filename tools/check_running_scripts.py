#!/usr/bin/env python3
"""
Check for specific bot scripts running by scanning process commandlines via psutil.
Prints a compact table of matches.
"""
import os
import psutil
import time
from collections import defaultdict

# Canonical script identifiers mapped to the patterns we expect in cmdlines.
# This makes sure alternative launch paths (e.g. tools/auto_retrain.py vs auto_retrain.py)
# are treated as a single logical process for duplicate detection.
TARGETS: dict[str, tuple[str, ...]] = {
    'start_bot.py': (
        'scripts/startup/start_bot.py',
        'start_bot.py',
    ),
    'monitor.py': (
        'scripts/helpers/monitor.py',
        'monitor.py',
    ),
    'trailing_bot.py': (
        'trailing_bot.py',
    ),
    'ai_supervisor.py': (
        'ai/ai_supervisor.py',
        'ai_supervisor.py',
    ),
    'auto_retrain.py': (
        'tools/auto_retrain.py',
        'auto_retrain.py',
    ),
    'dashboard_watchdog.py': (
        'dashboard_watchdog.py',
    ),
}


def _match_target(cmd: str) -> str | None:
    for canonical, patterns in TARGETS.items():
        for pattern in patterns:
            if pattern in cmd:
                return canonical
    return None

matches: list[dict[str, object]] = []
grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
pid_index: defaultdict[str, dict[int, dict[str, object]]] = defaultdict(dict)

for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid']):
    try:
        info = proc.info
        cmd = ' '.join(info.get('cmdline') or [])
        target = _match_target(cmd)
        if not target:
            continue

        try:
            cpu = proc.cpu_percent(interval=0.05)
        except Exception:
            cpu = None

        try:
            status = info.get('status') or proc.status()
        except Exception:
            status = 'unknown'

        try:
            created = info.get('create_time') or proc.create_time()
            created_fmt = time.ctime(created)
        except Exception:
            created_fmt = None

        record = {
            'pid': info.get('pid'),
            'name': info.get('name'),
            'ppid': info.get('ppid'),
            'status': status,
            'create_time': created_fmt,
            'cpu_percent': cpu,
            'cmdline': cmd,
            'matched_target': target,
        }
        matches.append(record)
        grouped[target].append(record)
        if isinstance(record['pid'], int):
            pid_index[target][int(record['pid'])] = record
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue

if not matches:
    print('No matching bot scripts found running.')
    raise SystemExit(0)

# Ignore wrapper processes that immediately spawn a child running the same script.
wrapper_pids: set[int] = set()
for name, pid_map in pid_index.items():
    for pid, record in pid_map.items():
        child = next((child_rec for child_rec in pid_map.values() if child_rec.get('ppid') == pid), None)
        if child:
            wrapper_pids.add(pid)

filtered_grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
for record in matches:
    pid = int(record['pid']) if record['pid'] is not None else None
    if pid is not None and pid in wrapper_pids:
        continue
    filtered_grouped[record['matched_target']].append(record)

print(f'Found {sum(len(v) for v in filtered_grouped.values())} effective processes for {len(filtered_grouped)} canonical targets.')

duplicates = {name: items for name, items in filtered_grouped.items() if len(items) > 1}
if duplicates:
    print('\n[WARNING] Duplicate instances detected:')
    for name, items in duplicates.items():
        print(f"  - {name}: {len(items)} processes")

print('\nProcess detail:')
for name in sorted(filtered_grouped.keys()):
    entries = filtered_grouped[name]
    label = f'{name} (x{len(entries)})'
    print(f'\n{name:=^80}')
    print(f'{label}')
    for m in entries:
        print(f"  PID={m['pid']} status={m['status']} cpu%={m['cpu_percent']} created={m['create_time']}")
        print(f"    cmdline: {m['cmdline']}")
