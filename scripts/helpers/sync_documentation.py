#!/usr/bin/env python3
"""
Documentation Sync Manager
Zorgt ervoor dat wijzigingen in één documentatiebestand automatisch worden weerspiegeld in alle gerelateerde bestanden.

Usage:
    python scripts/helpers/sync_documentation.py
    
    # Of als pre-commit hook:
    python scripts/helpers/sync_documentation.py --verify

Linked Documents:
    - docs/BOT_SYSTEM_OVERVIEW.md (master)
    - docs/TODO.md
    - docs/AUTONOMOUS_EXECUTION_PROMPT.md
    - CHANGELOG.md
    - README.md
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Linked documentation files
DOCS = {
    'overview': PROJECT_ROOT / 'docs' / 'BOT_SYSTEM_OVERVIEW.md',
    'todo': PROJECT_ROOT / 'docs' / 'TODO.md',
    'autonomous': PROJECT_ROOT / 'docs' / 'AUTONOMOUS_EXECUTION_PROMPT.md',
    'changelog': PROJECT_ROOT / 'CHANGELOG.md',
    'readme': PROJECT_ROOT / 'README.md',
}


def get_timestamp() -> str:
    """Get current timestamp in CET"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M CET')


def extract_last_updated(content: str) -> Optional[str]:
    """Extract 'Last Updated' timestamp from document"""
    match = re.search(r'\*\*Last Updated:\*\*\s+(.+?)(?:\n|$)', content)
    return match.group(1) if match else None


def update_last_updated(content: str, timestamp: str) -> str:
    """Update 'Last Updated' timestamp in document"""
    pattern = r'(\*\*Last Updated:\*\*\s+).+?(?=\n|$)'
    return re.sub(pattern, rf'\g<1>{timestamp}', content)


def extract_bot_status(trade_log_path: Path) -> Dict[str, any]:
    """Extract current bot status from trade_log.json"""
    try:
        with open(trade_log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        open_trades = data.get('open', [])
        closed_trades = data.get('closed', [])
        
        # Get balance (approximate from recent data)
        balance_eur = 0.0
        try:
            balance_file = PROJECT_ROOT / 'data' / 'bot_health.json'
            if balance_file.exists():
                with open(balance_file, 'r', encoding='utf-8') as f:
                    health = json.load(f)
                    balance_eur = health.get('balance_eur', 0.0)
        except Exception:
            pass
        
        return {
            'open_trades': len(open_trades),
            'balance_eur': balance_eur,
            'total_trades': len(closed_trades),
            'markets': [t.get('market', 'UNKNOWN') for t in open_trades[:5]],
        }
    except Exception as e:
        print(f"Warning: Could not extract bot status: {e}")
        return {
            'open_trades': 0,
            'balance_eur': 0.0,
            'total_trades': 0,
            'markets': [],
        }


def update_bot_status_in_docs(status: Dict[str, any]) -> None:
    """Update bot status in TODO.md and BOT_SYSTEM_OVERVIEW.md"""
    timestamp = get_timestamp()
    
    # Update TODO.md status line
    if DOCS['todo'].exists():
        content = DOCS['todo'].read_text(encoding='utf-8')
        
        # Update status line
        status_line = f"**Bot Status:** ✅ Running ({status['open_trades']} open trades, €{status['balance_eur']:.0f} balance)"
        content = re.sub(
            r'\*\*Bot Status:\*\*.*?(?=\n)',
            status_line,
            content
        )
        
        # Update timestamp
        content = update_last_updated(content, timestamp)
        
        DOCS['todo'].write_text(content, encoding='utf-8')
        print(f"✅ Updated bot status in TODO.md")
    
    # Update BOT_SYSTEM_OVERVIEW.md statistics section
    if DOCS['overview'].exists():
        content = DOCS['overview'].read_text(encoding='utf-8')
        
        # Update timestamp
        content = update_last_updated(content, timestamp)
        
        # Update statistics (if section exists)
        stats_pattern = r'(\*\*Current Bot Status.*?\n)([\s\S]*?)(\n---|\n## )'
        if re.search(stats_pattern, content):
            markets_str = ', '.join(status['markets']) if status['markets'] else 'None'
            new_stats = f"""- ✅ Running: Yes
- 📈 Open Trades: {status['open_trades']} ({markets_str})
- 💰 EUR Balance: €{status['balance_eur']:.2f}
- 📊 Total Trades: {status['total_trades']}
- 🔄 Last Updated: {timestamp}
"""
            content = re.sub(
                stats_pattern,
                rf'\g<1>{new_stats}\g<3>',
                content
            )
        
        DOCS['overview'].write_text(content, encoding='utf-8')
        print(f"✅ Updated bot status in BOT_SYSTEM_OVERVIEW.md")


def log_change_to_changelog(change_type: str, description: str, files_modified: List[str]) -> None:
    """Append a new entry to CHANGELOG.md"""
    timestamp = get_timestamp()
    
    if not DOCS['changelog'].exists():
        print("Warning: CHANGELOG.md not found")
        return
    
    content = DOCS['changelog'].read_text(encoding='utf-8')
    
    # Create new entry
    date_header = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    time_str = datetime.now(timezone.utc).strftime('%H:%M')
    
    # Check if today's session exists
    session_pattern = rf'## {date_header}:.*?\n'
    if not re.search(session_pattern, content):
        # Create new session header
        new_session = f"""## {date_header}: Documentation Update ({time_str} CET)

### Changes Made

| Time | Type | Details |
|------|------|---------|
| {time_str} | {change_type} | {description} |

### Files Modified
{chr(10).join(f'- `{f}`' for f in files_modified)}

---

"""
        # Insert after the linked documentation section
        link_section_end = content.find('---\n\n## ')
        if link_section_end != -1:
            # Find the next '---' after linked docs
            next_section = content.find('\n---\n', link_section_end + 5)
            if next_section != -1:
                content = content[:next_section + 5] + '\n' + new_session + content[next_section + 5:]
    else:
        # Append to existing session
        # Find the table and append row
        table_pattern = rf'(## {date_header}:.*?\| Time \| Type \| Details \|.*?\n\|-+\|-+\|-+\|.*?\n)(.*?)(\n###|\n---|\Z)'
        match = re.search(table_pattern, content, re.DOTALL)
        if match:
            new_row = f"| {time_str} | {change_type} | {description} |\n"
            content = re.sub(
                table_pattern,
                rf'\g<1>{new_row}\g<2>\g<3>',
                content,
                flags=re.DOTALL
            )
    
    DOCS['changelog'].write_text(content, encoding='utf-8')
    print(f"✅ Logged change to CHANGELOG.md")


def verify_cross_references() -> bool:
    """Verify that all cross-references are present in documents"""
    errors = []
    
    # Check TODO.md has cross-references
    if DOCS['todo'].exists():
        content = DOCS['todo'].read_text(encoding='utf-8')
        if 'BOT_SYSTEM_OVERVIEW.md' not in content:
            errors.append("TODO.md missing cross-reference to BOT_SYSTEM_OVERVIEW.md")
    
    # Check AUTONOMOUS_EXECUTION_PROMPT.md has cross-references
    if DOCS['autonomous'].exists():
        content = DOCS['autonomous'].read_text(encoding='utf-8')
        if 'BOT_SYSTEM_OVERVIEW.md' not in content:
            errors.append("AUTONOMOUS_EXECUTION_PROMPT.md missing cross-reference to BOT_SYSTEM_OVERVIEW.md")
    
    # Check CHANGELOG.md has cross-references
    if DOCS['changelog'].exists():
        content = DOCS['changelog'].read_text(encoding='utf-8')
        if 'BOT_SYSTEM_OVERVIEW.md' not in content:
            errors.append("CHANGELOG.md missing cross-reference to BOT_SYSTEM_OVERVIEW.md")
    
    # Check README.md has link to overview
    if DOCS['readme'].exists():
        content = DOCS['readme'].read_text(encoding='utf-8')
        if 'BOT_SYSTEM_OVERVIEW.md' not in content:
            errors.append("README.md missing link to BOT_SYSTEM_OVERVIEW.md")
    
    if errors:
        print("❌ Cross-reference verification failed:")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print("✅ All cross-references verified")
        return True


def sync_documentation(auto_update_status: bool = True, log_to_changelog: bool = False):
    """Main sync function"""
    print("🔄 Syncing documentation...")
    
    # 1. Verify cross-references
    verify_cross_references()
    
    # 2. Update bot status if requested
    if auto_update_status:
        trade_log_path = PROJECT_ROOT / 'trade_log.json'
        if trade_log_path.exists():
            status = extract_bot_status(trade_log_path)
            update_bot_status_in_docs(status)
        else:
            print("⚠️  trade_log.json not found, skipping bot status update")
    
    # 3. Log to changelog if requested
    if log_to_changelog:
        files_modified = [f.name for f in DOCS.values() if f.exists()]
        log_change_to_changelog(
            change_type="Documentation Sync",
            description="Automated documentation synchronization",
            files_modified=files_modified
        )
    
    print("✅ Documentation sync complete!")


if __name__ == '__main__':
    import sys
    
    if '--verify' in sys.argv:
        # Verification mode (for pre-commit hooks)
        success = verify_cross_references()
        sys.exit(0 if success else 1)
    elif '--status-only' in sys.argv:
        # Only update bot status
        trade_log_path = PROJECT_ROOT / 'trade_log.json'
        if trade_log_path.exists():
            status = extract_bot_status(trade_log_path)
            update_bot_status_in_docs(status)
    elif '--log' in sys.argv:
        # Full sync with changelog logging
        sync_documentation(auto_update_status=True, log_to_changelog=True)
    else:
        # Default: update status only
        sync_documentation(auto_update_status=True, log_to_changelog=False)
