# Small helper to list processes with full cmdline using psutil
import psutil


def main():
    rows = []
    for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
        try:
            info = p.info
            pid = info.get('pid')
            name = info.get('name')
            exe = info.get('exe') or ''
            cmdline = ' '.join(info.get('cmdline') or [])
            rows.append((pid, name, exe, cmdline))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Sort by pid for stable output
    for pid, name, exe, cmdline in sorted(rows, key=lambda r: r[0]):
        print(f"PID={pid}\tNAME={name}\nEXE={exe}\nCMD={cmdline}\n---")


if __name__ == '__main__':
    main()
