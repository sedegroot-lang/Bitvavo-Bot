"""
Prevent Windows multiprocessing spawn from creating duplicate processes.

This module must be imported at the VERY TOP of every script (before any other imports)
to prevent Windows spawn multiprocessing from re-executing the entire script.

Windows spawn works by:
1. Starting a new Python interpreter
2. Importing the target module
3. Executing code in if __name__ == '__main__' block

Without this guard, ALL import-time code executes twice (once in parent, once in child),
causing duplicate processes and resource conflicts.
"""
import sys
import os

# If this script is being imported (not run as main), AND we're on Windows,
# AND we're in a spawned multiprocessing context (parent process exists),
# we should exit immediately to prevent double execution.
#
# However, we CANNOT simply check __name__ here because this is a separate module.
# The real fix: each script must call check_spawn_guard() before any heavy imports.

def check_spawn_guard(script_name: str) -> None:
    """
    Call this at the TOP of your script (before heavy imports) to prevent
    Windows multiprocessing spawn from re-executing your entire script.
    
    Args:
        script_name: Name of your script (e.g., 'monitor.py')
    """
    # Only relevant on Windows
    if os.name != 'nt':
        return
    
    # If we're not the main script, something is trying to import us
    # This happens during Windows spawn - exit immediately
    if __name__ != '__main__':
        # We're being imported, not run directly - this is fine
        return
    
    # If BITVAVO_BOT_SPAWNED env var is set, we're in a spawn context
    # and should let the script run normally
    if os.environ.get('BITVAVO_BOT_SPAWNED') == '1':
        return
    
    # Set the flag for any children we spawn
    os.environ['BITVAVO_BOT_SPAWNED'] = '1'
