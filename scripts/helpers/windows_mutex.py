"""
Robust single instance checker using PID file with atomic operations.
Works reliably on Windows by combining file locking with process verification.
"""
import sys
import os
import time
import tempfile

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Global lock file handle
_lock_file_handle = None


def _is_process_running(pid):
    """Check if a process with given PID is running."""
    if HAS_PSUTIL:
        try:
            proc = psutil.Process(pid)
            # Check if it's a python process
            if 'python' in proc.name().lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def ensure_single_instance_or_exit(script_name):
    """
    Ensure only one instance of the script is running.
    Exits with code 1 if another instance is already running.
    
    Uses atomic file operations + PID checking for reliability.
    
    Args:
        script_name: Name of the script (e.g., 'start_bot.py')
    """
    global _lock_file_handle
    
    # Create locks directory in project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    locks_dir = os.path.join(project_root, 'locks')
    os.makedirs(locks_dir, exist_ok=True)
    
    # Clean script name for lock filename
    lock_name = script_name.replace('.py', '').replace('/', '_').replace('\\', '_')
    lock_file = os.path.join(locks_dir, f"{lock_name}.lock")
    
    current_pid = os.getpid()
    
    # Retry loop with exponential backoff
    max_retries = 10
    for attempt in range(max_retries):
        try:
            # Try to create lock file atomically using os.O_CREAT | os.O_EXCL
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            
            # Success! We created the file
            try:
                os.write(fd, str(current_pid).encode())
                os.close(fd)
                
                print(f"[SingleInstance] {script_name} acquired exclusive lock (PID={current_pid})")
                
                # Register cleanup
                import atexit
                def cleanup():
                    try:
                        if os.path.exists(lock_file):
                            # Verify it's our PID before deleting
                            with open(lock_file, 'r') as f:
                                file_pid = int(f.read().strip())
                            if file_pid == current_pid:
                                os.remove(lock_file)
                    except:
                        pass
                atexit.register(cleanup)
                
                return
            except Exception as e:
                os.close(fd)
                try:
                    os.remove(lock_file)
                except:
                    pass
                raise
                
        except FileExistsError:
            # Lock file exists - check if the process is still running
            try:
                with open(lock_file, 'r') as f:
                    existing_pid = int(f.read().strip())
                
                # Check if that process is still alive
                if _is_process_running(existing_pid):
                    # Process is alive!
                    print(f"[SingleInstance] {script_name} is already running (PID={existing_pid}). Exiting.")
                    sys.exit(1)
                else:
                    # Process is dead, remove stale lock file
                    print(f"[SingleInstance] Removing stale lock file (dead PID={existing_pid})")
                    try:
                        os.remove(lock_file)
                    except:
                        pass
                    # Retry
                    time.sleep(0.05 * (2 ** min(attempt, 3)))
                    continue
                    
            except (ValueError, IOError):
                # Corrupt lock file, try to remove
                try:
                    os.remove(lock_file)
                except:
                    pass
                time.sleep(0.05 * (2 ** min(attempt, 3)))
                continue
    
    # Failed after all retries
    print(f"[SingleInstance] ERROR: Could not acquire lock for {script_name} after {max_retries} attempts")
    sys.exit(1)
