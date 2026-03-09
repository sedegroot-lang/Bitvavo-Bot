#!/usr/bin/env python3
import subprocess, sys, datetime
from collections import defaultdict


def get_git_commits():
    cmd = ["git", "log", "--pretty=format:%an|%ae|%at", "--reverse"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        print("ERROR: git command failed:\n", p.stderr, file=sys.stderr)
        return []
    lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    commits = []
    for l in lines:
        try:
            name, email, ts = l.split('|')
            ts = int(ts)
            commits.append((name.strip(), email.strip(), ts))
        except Exception:
            continue
    return commits


def analyze_commits(commits, gap_seconds=7200):
    # group commits by author (name|email)
    authors = defaultdict(list)
    for name, email, ts in commits:
        key = f"{name} <{email}>"
        authors[key].append(ts)

    results = {}
    for author, times in authors.items():
        times.sort()
        first = times[0]
        last = times[-1]
        span_days = (last - first) / 86400.0
        # build sessions: gaps > gap_seconds break sessions
        sessions = []
        cur_start = times[0]
        cur_end = times[0]
        for t in times[1:]:
            if t - cur_end <= gap_seconds:
                cur_end = t
            else:
                sessions.append((cur_start, cur_end))
                cur_start = t
                cur_end = t
        sessions.append((cur_start, cur_end))
        total_session_seconds = sum((end - start) for start, end in sessions)
        # conservative extra time per commit (minutes)
        minutes_per_commit = 15
        extra_seconds = len(times) * minutes_per_commit * 60
        est_hours_sessions = total_session_seconds / 3600.0
        est_hours_with_commits = (total_session_seconds + extra_seconds) / 3600.0
        results[author] = {
            'commits': len(times),
            'first': datetime.datetime.utcfromtimestamp(first).isoformat() + 'Z',
            'last': datetime.datetime.utcfromtimestamp(last).isoformat() + 'Z',
            'span_days': span_days,
            'sessions_count': len(sessions),
            'total_session_hours': round(est_hours_sessions, 2),
            'estimated_hours_with_commit_overhead': round(est_hours_with_commits, 2),
        }
    return results


def main():
    commits = get_git_commits()
    if not commits:
        print('No commits found or git failed.')
        return 1
    res = analyze_commits(commits)
    # Print summary sorted by most commits
    sorted_authors = sorted(res.items(), key=lambda kv: kv[1]['commits'], reverse=True)
    total_commits = sum(v['commits'] for _, v in sorted_authors)
    print(f"Total commits in repo: {total_commits}\n")
    for author, info in sorted_authors:
        print(f"Author: {author}")
        print(f"  Commits: {info['commits']}")
        print(f"  First commit: {info['first']}")
        print(f"  Last commit:  {info['last']}")
        print(f"  Span (days):  {info['span_days']:.1f}")
        print(f"  Sessions:     {info['sessions_count']}")
        print(f"  Session-hours (sum of sessions): {info['total_session_hours']} h")
        print(f"  Estimated hours (sessions + 15 min/commit overhead): {info['estimated_hours_with_commit_overhead']} h")
        print("")
    return 0

if __name__ == '__main__':
    sys.exit(main())
