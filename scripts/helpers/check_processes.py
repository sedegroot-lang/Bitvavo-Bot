#!/usr/bin/env python3
"""Check hoeveel bot processen er draaien en of er duplicaten zijn."""
import subprocess
import re
from collections import Counter

# Haal alle python.exe processen op via WMI
cmd = 'wmic process where "name=\'python.exe\'" get ProcessId,CommandLine'
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

# Parse output
scripts = []
for line in result.stdout.split('\n'):
    if 'python' in line.lower():
        # Extract script naam uit commandline
        match = re.search(r'([a-z_]+\.py)', line.lower())
        if match:
            scripts.append(match.group(1))

# Tel scripts
counts = Counter(scripts)

print("\n=== BOT PROCESSEN STATUS ===\n")
print("Draaiende scripts:")
for script, count in sorted(counts.items()):
    print(f"  {script}: {count}x")

total = len(scripts)
duplicates = sum(1 for c in counts.values() if c > 1)

print(f"\nTotaal: {total} processen")
print(f"Duplicaten: {duplicates}")

if duplicates == 0 and total == 5:
    print("\n✓ PERFECT! Elk script draait precies 1x!\n")
elif duplicates == 0:
    print(f"\n✓ Geen duplicaten (verwacht: 5, gevonden: {total})\n")
else:
    print("\n✗ ER ZIJN NOG DUPLICATEN!\n")
