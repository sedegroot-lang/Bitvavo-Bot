# Contributing to Bitvavo Trading Bot

Bedankt voor je interesse in het bijdragen aan dit project! 🎉

## 🚀 Quick Start

1. **Clone de repository**
   ```bash
   git clone <repository-url>
   cd bitvavo-bot
   ```

2. **Maak een virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   # of
   source .venv/bin/activate  # Linux/Mac
   ```

3. **Installeer dependencies**
   ```bash
   pip install -r requirements.txt
   pip install pre-commit pytest mypy black isort flake8
   ```

4. **Installeer pre-commit hooks**
   ```bash
   pre-commit install
   ```

## 📁 Project Structuur

```
bitvavo-bot/
├── trailing_bot.py      # Hoofd trading bot
├── core/                # Kern modules (cache, price engine, etc.)
├── modules/             # Business logic modules
├── ai/                  # AI/ML componenten
├── tools/               # Dashboard en utilities
├── tests/               # Unit tests
├── config/              # Configuratie bestanden
├── data/                # Data opslag
├── scripts/             # Startup en utility scripts
└── docs/                # Documentatie
```

## 🧪 Tests Uitvoeren

```bash
# Alle tests
pytest

# Specifieke test file
pytest tests/test_core_cache.py -v

# Met coverage
pytest --cov=core --cov=modules
```

## 📝 Code Stijl

- **Python 3.13+** - Gebruik moderne Python features
- **Type hints** - Voeg type hints toe aan publieke functies
- **Docstrings** - Documenteer functies met Google-style docstrings
- **Line length** - Max 120 karakters
- **Formatting** - Black formatter
- **Imports** - isort voor import ordering

### Voorbeeld functie:

```python
def calculate_profit(
    entry_price: float,
    exit_price: float,
    amount: float,
    fees: float = 0.0025
) -> float:
    """
    Bereken de winst/verlies van een trade.
    
    Args:
        entry_price: Aankoopprijs per eenheid
        exit_price: Verkoopprijs per eenheid
        amount: Aantal eenheden
        fees: Fee percentage (default 0.25%)
        
    Returns:
        Netto winst/verlies in EUR
        
    Raises:
        ValueError: Als entry_price of amount <= 0
    """
    if entry_price <= 0 or amount <= 0:
        raise ValueError("entry_price en amount moeten > 0 zijn")
    
    gross = (exit_price - entry_price) * amount
    fee_cost = (entry_price + exit_price) * amount * fees
    return gross - fee_cost
```

## 🔧 Nieuwe Features Toevoegen

1. **Maak een feature branch**
   ```bash
   git checkout -b feature/mijn-nieuwe-feature
   ```

2. **Schrijf tests eerst** (TDD)
   - Maak een test file in `tests/`
   - Zorg dat tests falen voordat je implementeert

3. **Implementeer de feature**
   - Volg de bestaande code stijl
   - Voeg type hints en docstrings toe
   - Update documentatie indien nodig

4. **Run tests en linting**
   ```bash
   pytest
   pre-commit run --all-files
   ```

5. **Commit met duidelijke message**
   ```bash
   git commit -m "feat: voeg X functionaliteit toe"
   ```

## 🐛 Bug Reports

Gebruik de issue tracker met:
- Duidelijke beschrijving van het probleem
- Stappen om te reproduceren
- Verwacht vs. daadwerkelijk gedrag
- Log output (geanonimiseerd)
- Python versie en OS

## 📋 Commit Conventie

We gebruiken [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - Nieuwe feature
- `fix:` - Bug fix
- `docs:` - Documentatie
- `style:` - Formatting (geen code wijziging)
- `refactor:` - Code refactoring
- `test:` - Tests toevoegen/wijzigen
- `chore:` - Maintenance taken

## ⚠️ Belangrijke Richtlijnen

### Veiligheid
- **NOOIT** API keys of secrets committen
- Gebruik `.env` voor gevoelige data
- Check voor hardcoded credentials

### Performance
- Vermijd N+1 API calls - gebruik batch operaties
- Implementeer caching waar mogelijk
- Profile code voor bottlenecks

### Error Handling
- **NOOIT** bare `except: pass` gebruiken
- Log alle exceptions met context
- Gebruik specifieke exception types

## 🤝 Review Process

1. Maak een Pull Request
2. Automated checks moeten slagen
3. Code review door maintainer
4. Merge na approval

## 📞 Vragen?

Open een issue met het label `question` voor vragen over de codebase.

---

Bedankt voor je bijdrage! 🙌
