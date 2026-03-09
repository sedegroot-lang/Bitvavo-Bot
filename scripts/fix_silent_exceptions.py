#!/usr/bin/env python3
"""Fix silent except:pass blocks by adding appropriate logging.

For each file, this script:
1. Finds all `except ... : pass` patterns
2. Determines severity based on context (try-block analysis)
3. Replaces `pass` with `log(f"...: {e}", level=...)` 

If the except doesn't capture `e`, it adds `as e`.
"""
import re
import sys
from pathlib import Path

# Keywords that indicate financial-critical code
CRITICAL_KEYWORDS = {
    'sell', 'buy', 'order', 'place_sell', 'open_trade', 'market_order',
    'stop_loss', 'trailing', 'price', 'amount', 'invested', 'profit',
    'cost_basis', 'fill', 'balance', 'reserve', 'entry_price',
    'drawdown', 'emergency', 'force_close', 'dca', 'headroom',
}

HIGH_KEYWORDS = {
    'sync', 'config', 'state', 'save', 'load', 'write', 'read',
    'heartbeat', 'history', 'audit', 'apply', 'suggest', 'migrate',
    'reservation', 'guardrail', 'market', 'portfolio', 'api',
}

MEDIUM_KEYWORDS = {
    'metrics', 'monitor', 'health', 'debug', 'report', 'publish',
    'display', 'status', 'filter', 'block_reason',
}

# Log function names per file
LOG_FUNCS = {
    'trailing_bot.py': 'log',
    'ai/ai_supervisor.py': '_dbg',
    'modules/trading_dca.py': 'self._log',
}


def classify_try_block(try_lines: str) -> str:
    """Classify a try block by severity."""
    lower = try_lines.lower()
    for kw in CRITICAL_KEYWORDS:
        if kw in lower:
            return 'error'
    for kw in HIGH_KEYWORDS:
        if kw in lower:
            return 'warning'
    for kw in MEDIUM_KEYWORDS:
        if kw in lower:
            return 'warning'
    return 'debug'


def extract_context_label(try_lines: str) -> str:
    """Extract a short label from the try block for the log message."""
    # Find the first meaningful assignment or function call
    lines = [l.strip() for l in try_lines.strip().split('\n') if l.strip() and not l.strip().startswith('#')]
    if not lines:
        return "operation"
    
    # Look for function calls
    for line in lines:
        m = re.search(r'(\w+)\s*\(', line)
        if m and m.group(1) not in ('if', 'for', 'while', 'with', 'open', 'float', 'int', 'str', 'dict', 'list', 'max', 'min', 'round', 'bool', 'len', 'isinstance', 'range', 'set'):
            return m.group(1)
        # Look for assignments
        m = re.search(r"(\w+)\s*[\['].*?[\]']\s*=", line)
        if m:
            return m.group(1) + " update"
        m = re.search(r"(\w+)\s*=", line)
        if m and m.group(1) not in ('_', 'e'):
            return m.group(1)
    
    return lines[0][:40].replace("'", "").replace('"', '')


def fix_file(filepath: str, log_func: str) -> int:
    """Fix all silent except:pass blocks in a file. Returns count of fixes."""
    with open(filepath, encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    fixes = 0
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Match: except [Type] [as var]:
        m = re.match(r'^(\s*)except\s*([\w.,\s()]*?)(?:\s+as\s+(\w+))?\s*:\s*$', line)
        if m:
            indent = m.group(1)
            exc_type = m.group(2).strip() or 'Exception'
            var_name = m.group(3)
            
            # Check if next non-empty line is `pass`
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            
            if j < len(lines) and lines[j].strip() == 'pass':
                # Find the try block above
                try_start = None
                for k in range(i - 1, max(i - 30, -1), -1):
                    if lines[k].strip().startswith('try:'):
                        try_start = k
                        break
                
                try_content = '\n'.join(lines[try_start + 1:i]) if try_start else ''
                level = classify_try_block(try_content)
                label = extract_context_label(try_content)
                
                # Ensure we have `as e`
                if not var_name:
                    var_name = 'e'
                    # Rewrite except line to include `as e`
                    if exc_type:
                        lines[i] = f'{indent}except {exc_type} as {var_name}:'
                    else:
                        lines[i] = f'{indent}except Exception as {var_name}:'
                
                # Replace pass with log
                body_indent = indent + '    '
                log_msg = f'{label} failed'
                
                if filepath.endswith('ai_supervisor.py'):
                    # _dbg uses different signature: _dbg(msg)
                    lines[j] = f'{body_indent}_dbg(f"{log_msg}: {{{var_name}}}")'
                elif filepath.endswith('trading_dca.py') and 'self' in log_func:
                    lines[j] = f'{body_indent}self._log(f"{log_msg}: {{{var_name}}}", level=\'{level}\')'
                else:
                    lines[j] = f'{body_indent}log(f"{log_msg}: {{{var_name}}}", level=\'{level}\')'
                
                fixes += 1
        
        i += 1
    
    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    
    return fixes


def main():
    files = [
        ('trailing_bot.py', 'log'),
        ('ai/ai_supervisor.py', '_dbg'),
        ('modules/trading_dca.py', 'self._log'),
    ]
    
    total = 0
    for filepath, log_func in files:
        if not Path(filepath).exists():
            print(f"SKIP: {filepath} not found")
            continue
        count = fix_file(filepath, log_func)
        print(f"{filepath}: fixed {count} silent exceptions")
        total += count
    
    print(f"\nTotal: {total} silent exceptions fixed")


if __name__ == '__main__':
    main()
