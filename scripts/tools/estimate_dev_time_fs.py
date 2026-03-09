#!/usr/bin/env python3
import os, sys, time, datetime
from pathlib import Path

EXCLUDE_DIRS = {'.git', '.venv', 'logs', 'backups', 'auto_updates', 'archive', '__pycache__', 'backups', '.pytest_cache', '.github', 'tests', 'docs'}


def collect_mtimes(root):
    times = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune excluded dirs
        parts = Path(dirpath).parts
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        for fn in filenames:
            if fn.endswith(('.pyc', '.pyo', '.log', '.jsonl')):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                mt = os.path.getmtime(fp)
                times.append(mt)
            except Exception:
                continue
    return sorted(times)


def analyze_times(times, gap_seconds=7200, min_session_seconds=300):
    if not times:
        return None
    sessions = []
    start = times[0]
    end = times[0]
    for t in times[1:]:
        if t - end <= gap_seconds:
            end = t
        else:
            sessions.append((start, end))
            start = t
            end = t
    sessions.append((start, end))
    total_seconds = 0
    for s,e in sessions:
        dur = max(min_session_seconds, e - s)
        total_seconds += dur
    return {
        'sessions_count': len(sessions),
        'total_seconds': total_seconds,
        'first': datetime.datetime.utcfromtimestamp(times[0]).isoformat()+'Z',
        'last': datetime.datetime.utcfromtimestamp(times[-1]).isoformat()+'Z',
    }


def main():
    repo_root = Path(__file__).resolve().parents[2]
    times = collect_mtimes(str(repo_root))
    stats = analyze_times(times)
    if not stats:
        print('No file modification times found.')
        return 1
    hours = stats['total_seconds'] / 3600.0
    print(f"Estimated active editing sessions: {stats['sessions_count']}")
    print(f"First modification: {stats['first']}")
    print(f"Last modification:  {stats['last']}")
    print(f"Estimated total active hours (from file mtimes, gaps<=2h merged, min session 5min): {hours:.2f} h")
    print('\nNotes:')
    print('- This is a filesystem-based heuristic; it estimates active editing time by grouping file modification timestamps into sessions.')
    print('- It does not count review, planning, reading, or work done outside this filesystem.')
    print('- Excluded directories: ' + ', '.join(sorted(EXCLUDE_DIRS)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
