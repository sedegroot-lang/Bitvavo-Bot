"""
Bitvavo Bot — Eerste keer setup wizard
Dubbelklik setup.bat om dit te starten.
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / '.env'
ENV_EXAMPLE = BASE_DIR / '.env.example'
REQUIREMENTS = BASE_DIR / 'requirements.txt'

AFFILIATE_LINK = 'https://bitvavo.com/invite?a=B8942E4528'
BTC_ADDRESS = '1DUCu4ZGgKHZr22DvAxuWKBujcfpCLJoNy'

# ── kleur helpers (werkt op Windows 10+) ──────────────────────────────────────
os.system('')  # enable ANSI on Windows
GREEN  = '\033[92m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
RED    = '\033[91m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

def banner():
    print()
    print(f"{BOLD}{CYAN}{'═' * 58}{RESET}")
    print(f"{BOLD}{CYAN}   Bitvavo Trading Bot — Setup Wizard{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 58}{RESET}")
    print()

def step(n, text):
    print(f"{BOLD}{YELLOW}[Stap {n}]{RESET} {text}")

def ok(text):
    print(f"  {GREEN}✓ {text}{RESET}")

def warn(text):
    print(f"  {YELLOW}⚠ {text}{RESET}")

def error(text):
    print(f"  {RED}✗ {text}{RESET}")

def ask(prompt, secret=False):
    """Prompt the user for input. secret=True hides typed characters."""
    if secret:
        import getpass
        return getpass.getpass(f"  → {prompt}: ").strip()
    return input(f"  → {prompt}: ").strip()

def ask_yn(prompt, default='j'):
    """Ask a yes/no question."""
    hint = '[J/n]' if default == 'j' else '[j/N]'
    answer = input(f"  → {prompt} {hint}: ").strip().lower()
    if answer == '':
        return default == 'j'
    return answer in ('j', 'y', 'ja', 'yes')


# ── Stap 1 — Bitvavo account check ───────────────────────────────────────────
def step_bitvavo():
    """
    Guide the user through Bitvavo account setup.
    Returns True if the user registered via affiliate link (new account),
    False if they already had an account.
    """
    step(1, 'Bitvavo account')
    print()
    print(f"  Deze bot werkt uitsluitend met een Bitvavo account.")
    print()
    has_account = ask_yn('Heb je al een Bitvavo account?')
    if not has_account:
        print()
        print(f"  {BOLD}Registreer gratis via onze link (0 kosten, ~5 min):{RESET}")
        print(f"  {CYAN}👉  {AFFILIATE_LINK}{RESET}")
        print()
        print(f"  Stappen:")
        print(f"  1. Open bovenstaande link in je browser")
        print(f"  2. Maak een gratis account aan")
        print(f"  3. Verifieer je identiteit (KYC — wettelijk verplicht)")
        print(f"  4. Kom terug naar dit venster")
        print()
        input("  Druk op ENTER zodra je account aangemaakt is...")
        ok("Goed! Affiliate link gebruikt — bedankt voor de steun 💛")
        print()
        return True  # nieuwe gebruiker via affiliate
    else:
        ok("Bestaand account — geen actie nodig")
        print()
        return False  # bestaande gebruiker


# ── Stap 2 — API keys ─────────────────────────────────────────────────────────
def step_api_keys():
    step(2, 'Bitvavo API sleutels aanmaken')
    print()
    print(f"  1. Ga naar: {CYAN}https://bitvavo.com/nl/account/api{RESET}")
    print(f"  2. Maak een nieuwe API sleutel aan")
    print(f"  3. Rechten: {BOLD}Lezen + Handelen{RESET} (GEEN Opnemen)")
    print(f"  4. Kopieer de Key en Secret — je ziet de Secret maar één keer!")
    print()
    input("  Druk op ENTER zodra je de API sleutels hebt...")
    print()

    api_key = ''
    api_secret = ''

    while not api_key:
        api_key = ask('API Key (begint meestal met letters/cijfers)')
        if not api_key:
            warn("API Key mag niet leeg zijn.")

    while not api_secret:
        api_secret = ask('API Secret (verborgen invoer)', secret=True)
        if not api_secret:
            warn("API Secret mag niet leeg zijn.")

    ok("API sleutels ontvangen")
    print()
    return api_key, api_secret


# ── Stap 3 — .env aanmaken ────────────────────────────────────────────────────
def step_create_env(api_key, api_secret, is_new_user=False):
    """
    Write .env file with API credentials.
    For new users (registered via affiliate link), also stores the affiliate
    code so the bot can log/identify affiliate-sourced installs.
    """
    step(3, '.env bestand aanmaken')
    print()

    if ENV_FILE.exists():
        overwrite = ask_yn('.env bestaat al — overschrijven?', default='n')
        if not overwrite:
            warn(".env niet overschreven — bestaande config blijft intact")
            print()
            return

    # Lees .env.example als basis
    if ENV_EXAMPLE.exists():
        template = ENV_EXAMPLE.read_text(encoding='utf-8')
    else:
        template = (
            "BITVAVO_API_KEY=\n"
            "BITVAVO_API_SECRET=\n"
        )

    # Vervang placeholders
    template = template.replace('your_api_key_here', api_key)
    template = template.replace('your_api_secret_here', api_secret)

    # Affiliate code: schrijf voor nieuwe gebruikers, verwijder lege regel anders
    lines = []
    for line in template.splitlines():
        if line.startswith('BITVAVO_AFFILIATE_CODE='):
            if is_new_user:
                lines.append(f'BITVAVO_AFFILIATE_CODE=B8942E4528')
            # bestaande gebruikers: regel weglaten
            continue
        lines.append(line)
    result = '\n'.join(lines)

    ENV_FILE.write_text(result, encoding='utf-8')
    ok(f".env aangemaakt in {ENV_FILE}")
    if is_new_user:
        ok("Affiliate code opgeslagen in .env")
    print()


# ── Stap 4 — dependencies installeren ────────────────────────────────────────
def step_install_deps():
    step(4, 'Python packages installeren')
    print()

    if not REQUIREMENTS.exists():
        warn("requirements.txt niet gevonden — skip")
        print()
        return

    # Probeer pip in de .venv, anders de system pip
    venv_pip = BASE_DIR / '.venv' / 'Scripts' / 'pip.exe'
    pip_cmd = str(venv_pip) if venv_pip.exists() else sys.executable + ' -m pip'

    print(f"  Installeren via: {pip_cmd}")
    print(f"  (Dit kan 1-2 minuten duren...)")
    print()

    try:
        if venv_pip.exists():
            cmd = [str(venv_pip), 'install', '-r', str(REQUIREMENTS), '-q']
        else:
            cmd = [sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS), '-q']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            ok("Alle packages geïnstalleerd")
        else:
            error("Installatie mislukt:")
            print(result.stderr[:400])
    except Exception as e:
        error(f"Fout: {e}")
    print()


# ── Stap 5 — klaar ────────────────────────────────────────────────────────────
def step_finish():
    print(f"{BOLD}{GREEN}{'═' * 58}{RESET}")
    print(f"{BOLD}{GREEN}   ✓  Setup voltooid! Bot is klaar voor gebruik.{RESET}")
    print(f"{BOLD}{GREEN}{'═' * 58}{RESET}")
    print()
    print(f"  {BOLD}Bot starten:{RESET}  dubbelklik  start_automated.bat")
    print(f"  {BOLD}Dashboard:{RESET}    http://localhost:5001")
    print()
    print(f"  {YELLOW}💛 Vind je de bot waardevol? Doneer via BTC:{RESET}")
    print(f"  {CYAN}{BTC_ADDRESS}{RESET}")
    print()

    start_now = ask_yn('Bot nu direct starten?')
    if start_now:
        bat = BASE_DIR / 'start_automated.bat'
        if bat.exists():
            os.startfile(str(bat))
            ok("Bot wordt gestart in nieuw venster...")
        else:
            warn("start_automated.bat niet gevonden")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    banner()
    try:
        is_new_user = step_bitvavo()
        api_key, api_secret = step_api_keys()
        step_create_env(api_key, api_secret, is_new_user=is_new_user)
        step_install_deps()
        step_finish()
    except KeyboardInterrupt:
        print()
        print()
        warn("Setup afgebroken. Voer setup.bat opnieuw uit om verder te gaan.")
        print()
    input("Druk op ENTER om dit venster te sluiten...")


if __name__ == '__main__':
    main()
