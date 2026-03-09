"""
Windows Multiprocessing Spawn Guard

On Windows, multiprocessing uses 'spawn' mode which re-imports the module in a new interpreter.
This causes the entire script to execute twice - once in parent (venv), once in child (system Python).

This guard detects if we're a spawned child using system Python and exits early.
"""
import sys
import os

def is_spawned_duplicate():
    """
    Detect if this is a Windows spawn duplicate (system Python child of venv parent).
    
    Returns:
        True if this is a duplicate spawn that should exit
    """
    if os.name != 'nt':
        return False
    
    # Check if we're system Python but parent was venv Python
    exe_path = sys.executable.lower()
    is_system = 'appdata' in exe_path or 'program files' in exe_path
    is_venv = '.venv' in exe_path or 'virtualenv' in exe_path
    
    # If we're system Python, check if BITVAVO_PYTHON_PATH points to venv
    venv_path = os.environ.get('BITVAVO_PYTHON_PATH', '').lower()
    parent_was_venv = '.venv' in venv_path
    
    # If parent was venv but we're system, we're a spawn duplicate
    if parent_was_venv and is_system:
        return True
    
    return False

def exit_if_spawn_duplicate(script_name: str):
    """
    Exit immediately if this is a Windows spawn duplicate.
    
    Call this at the TOP of your script, before any heavy imports.
    
    Args:
        script_name: Name of the script (for debugging)
    """
    if is_spawned_duplicate():
        # Silently exit - this is expected Windows behavior
        sys.exit(0)
