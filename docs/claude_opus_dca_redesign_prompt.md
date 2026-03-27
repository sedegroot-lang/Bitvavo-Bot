# Prompt voor Claude Opus — DCA & Trade State Redesign

---

## Achtergrond & Frustratie

Ik heb een Python-based crypto trailing-stop trading bot voor de Bitvavo exchange.
De afgelopen **maanden** blijven dezelfde soort bugs terugkomen rond DCA-tracking en trade state.
Elke fix introduceert een nieuwe edge case. Ik wil dat jij dit **eens en voor altijd oplost** —
ofwel door de bestaande code grondig te herstellen, ofwel door een compleet nieuw systeem te ontwerpen
dat de problemen architectureel onmogelijk maakt.

---

## De aanhoudende problemen (alle echt opgetreden)

### Probleem 1: `dca_buys` wordt verkeerd ingesteld bij sync/restart
- `modules/sync_validator.py` zette `dca_buys = max(1, buy_order_count)` waarbij `buy_order_count`
  **alle historische orders** van de markt bevat (ook afgesloten posities van weken terug).
  Resultaat: XRP toonde `dca_buys=17` terwijl er 0 echte DCAs waren uitgevoerd.
- `bot/sync_engine.py` deed periodiek een herberekening en zette `dca_buys = buy_order_count - 1`,
  waardoor de fix elke 4 uur teniet werd gedaan.
- `modules/trade_store.py` weigerde `dca_buys` te verlagen "om duplicate DCA te voorkomen" —
  ook als `dca_events` leeg was.

### Probleem 2: Cascading DCAs (3 buys op dezelfde prijs in 2 minuten)
- DCA-target werd berekend op basis van `buy_price` (gewogen gemiddelde).
- Na elke DCA daalt `buy_price` → de volgende DCA triggert meteen → cascade.
- Resultaat: €175 van €178 balance verbrand in 2 minuten (NEAR-EUR + ALGO-EUR).
- Fix: `last_dca_price` gebruiken als referentie, maar dit is alsnog fragiel.

### Probleem 3: `invested_eur` klopt niet na externe buys (handmatige DCA door mij)
- De bot houdt `invested_eur` bij in de trade state, maar als ik zelf handmatig bijkoop
  via Bitvavo's interface (externe DCA), weet de bot daar niets van.
- `derive_cost_basis()` werd gefilterd op `opened_ts` (bot restart timestamp, niet de echte
  eerste koop) → miste eerdere orders.
- `bot/sync_engine.py` had 3 conflicterende sync-checks die elkaar saboteerden.
- Dashboard gebruikte een `max()` hack die echte fouten maskeerde.

### Probleem 4: `dca_buys` ↔ `dca_events` inconsistentie bij restart
- `dca_events` is een lijst van DCA-events met prijs/bedrag/timestamp.
- `dca_buys` is een integer teller.
- Na bot restart gaan `dca_events` soms verloren (of worden niet geserialiseerd),
  maar `dca_buys` wel → GUARD 5 in `trailing_bot.py` reduceerde `dca_buys` naar 0
  terwijl er wél echte DCAs waren gedaan → bot koopt opnieuw op dezelfde niveaus.
- Maar als GUARD 5 de andere kant op corrigeert, gaat er iets anders mis.

### Probleem 5: GUARD NameError die de hele fix kapot maakte
- GUARD 5 in `trailing_bot.py` refereerde aan `dca_max_now` (bestaat niet),
  crashte silently → deed nooit iets → `dca_buys=17` bleef maanden staan.

### Probleem 6: FIFO cost basis contamineert via crypto dust
- FIFO-algoritme in `modules/cost_basis.py` resette de positie alleen bij `amount <= 1e-8`.
- Crypto dust van oude posities (bijv. 0.01 XRP = €0.01 waard) bleef boven die threshold.
- Resultaat: oude goedkope koopprijzen uit maanden geleden bloedden door in de huidige kosten
  → `invested_eur=€41.86` terwijl de echte kosten €66.95 waren (+60% fout).

---

## Hoe het systeem nu werkt (architectuur)

### Trade data structuur (Python dict, opgeslagen in `data/trade_log.json`)
```python
trade = {
    # Core positie data
    "buy_price": 1.23,          # gewogen gemiddelde aankoopprijs (muteert bij DCAs)
    "amount": 150.0,            # huidige hoeveelheid tokens
    "invested_eur": 184.50,     # totaal geïnvesteerd EUR (inclusief fees)
    "initial_invested_eur": 50.0,  # IMMUTABLE: eerste initiële aankoop
    "total_invested_eur": 184.50,  # cumulatief (inclusief alle DCAs)
    "highest_price": 1.45,      # high-water mark voor trailing stop
    
    # DCA tracking — DE PROBLEMATISCHE VELDEN
    "dca_buys": 3,              # integer teller — MOET gelijk zijn aan len(dca_events)
    "dca_max": 5,               # max DCAs voor deze trade
    "dca_events": [             # lijst van uitgevoerde DCA events
        {
            "ts": 1711234567.0,
            "price": 1.15,
            "eur_amount": 40.0,
            "tokens": 34.78,
            "dca_level": 1
        },
        # ... meer events
    ],
    "last_dca_price": 1.08,     # prijs van de laatste DCA (referentie voor volgende trigger)
    "dca_next_price": 1.03,     # voorberekende volgende DCA trigger prijs
    "dca_drop_pct": 0.025,      # % daling voor eerste DCA (2.5%)
    "dca_amount_eur": 40.0,     # EUR bedrag per DCA (per-trade override)
    
    # Timestamps
    "opened_ts": 1711100000.0,  # Unix timestamp eerste aankoop
    "timestamp": "2024-03-22T...",
    "synced_at": 1711200000.0,  # Wanneer positie voor het laatst gesynchroniseerd is
    
    # Metadata
    "market": "NEAR-EUR",
    "score": 3.2,
    "opened_regime": "aggressive",
}
```

### DCA uitvoering (`modules/trading_dca.py`)
- `DCAManager.handle_trade()` wordt elke ~25s aangeroepen per open trade
- Bepaalt of DCA moet triggeren op basis van `last_dca_price * (1 - drop_pct * multiplier^index)`
- Voert de buy order uit via `ctx.place_buy()`
- Werkt `dca_buys`, `dca_events`, `buy_price`, `amount`, `invested_eur`, `last_dca_price` bij
- Slaat trade state op via `ctx.save_trades()`

### DCA Guards in `trailing_bot.py` (`validate_and_repair_trades()`)
- GUARD 1: `dca_buys > dca_max` → cap op `dca_max`
- GUARD 4: `dca_buys` veld ontbreekt → set op 0
- GUARD 5: `dca_buys` ↔ `dca_events` consistentie (recent gefixed, maar logica is complex)

### Sync systemen (er zijn er twee die met elkaar botsen)
1. `modules/trading_sync.py` — achtergrond thread, vergelijkt Bitvavo balances met open_trades
2. `bot/sync_engine.py` — in de main loop, re-derives cost basis elke 4 uur

### Cost basis derivatie (`modules/cost_basis.py`)
- Haalt alle order history op van Bitvavo API
- FIFO algoritme om huidige positie te reconstrueren
- Calculeert `invested_eur`, `buy_price`, `amount` vanuit echte orders

---

## Manuele DCA's door mij (het onopgeloste probleem)

Ik koop soms **handmatig** bij via de Bitvavo interface als de markt extra sterk daalt.
Dit is een normale, gewenste feature. Het systeem moet hier mee omgaan:

1. **De bot detecteert een hogere `amount`** bij de volgende sync (Bitvavo balance)
2. **`invested_eur` moet opnieuw berekend worden** (FIFO over volledige order history)
3. **`dca_buys` moet ophogen** — mijn handmatige koop telt als een DCA niveau
4. **`dca_events` moet een entry krijgen** voor de handmatige koop
5. **`last_dca_price` moet bijgewerkt worden** zodat de volgende bot-DCA correct triggert
6. **`dca_next_price` moet herberekend worden** vanaf mijn handmatige koopprijs

Het huidige systeem doet dit verkeerd of helemaal niet. Na een handmatige koop:
- `dca_buys` gaat soms omhoog maar `dca_events` krijgt geen entry
- Of `dca_buys` wordt gereset naar 0 door een guard
- Of de bot triggert meteen opnieuw op hetzelfde niveau omdat `last_dca_price` niet bijgewerkt is

---

## Wat ik wil

### Optie A: Grondig herstel van het bestaande systeem
Analyseer alle bovenstaande problemen en schrijf een **bulletproof** implementatie die:
- Een **single source of truth** heeft voor DCA state (niet 3 systemen die elkaar tegenwerken)
- **Handmatige DCAs correct detecteert en verwerkt** via order history vergelijking
- **Nooit** `dca_buys` afleidt van historische `buy_order_count`
- **Atomisch** trade state bijwerkt (geen partial writes waarbij `dca_buys` en `dca_events` desyncen)
- **Guards** die werkelijk werken (geen NameErrors, geen conflicten)
- Na elke bot restart correct **herstelt** vanuit `dca_events` (niet vanuit de integer teller)

### Optie B: Complete redesign
Bedenk een nieuw architectuur waarbij deze bugs **structureel onmogelijk** zijn:
- Misschien: DCA state volledig afleiden vanuit order history (geen mutable counters)
- Misschien: event sourcing patroon waarbij `dca_events` de enige bron van waarheid is
- Misschien: aparte `ExternalBuyDetector` die handmatige buys verwerkt
- Misschien: transactional state updates zodat `dca_buys` en `dca_events` nooit desyncen

---

## Vereisten voor de oplossing

1. **Python 3.13, Windows-first** (thread-based timeouts, geen asyncio)
2. **Bestaande Bitvavo API** (`safe_call()` wrapper, retries, circuit breaker)
3. **Trade state is een plain Python dict** opgeslagen in `data/trade_log.json`
4. **Config** via `modules/config.py` (dict, UPPER_SNAKE_CASE keys)
5. **Geen afhankelijkheid van externe databases** (TinyDB is aanwezig maar minimaal gebruikt)
6. **Thread-safe** — bot is multi-threaded met `state.trades_lock` (RLock)
7. **Handmatige DCAs door de gebruiker moeten werken** — niet genegeerd of gecrasht
8. **`dca_buys == len(dca_events)` ALTIJD** (invariant, nooit een exception)
9. **Na restart volledig herstelbaar** vanuit `data/trade_log.json`
10. **Backward compatible** met bestaande closed trades in `data/trade_archive.json`

---

## Simuleer de volgende scenario's

Schrijf concrete Python code die de volgende scenario's correct afhandelt:

### Scenario 1: Bot DCA (normaal geval)
- Open trade: `buy_price=1.20, amount=100, dca_buys=0, dca_events=[]`
- Marktprijs daalt naar 1.17 (2.5% drop)
- Bot voert DCA uit van €40 op prijs 1.17
- Verwacht na DCA: `dca_buys=1, dca_events=[{price:1.17, ...}], last_dca_price=1.17`

### Scenario 2: Handmatige DCA door gebruiker
- Open trade: `buy_price=1.20, amount=100, dca_buys=1, dca_events=[{price:1.17}]`
- Gebruiker koopt handmatig 50 extra tokens op Bitvavo voor €57 (prijs 1.14)
- Bot detecteert bij sync: `amount` is nu 150 i.p.v. 100
- Verwacht na sync: `dca_buys=2, dca_events=[{price:1.17}, {price:1.14, source:"manual"}], last_dca_price=1.14`
- `buy_price` correct herberekend als gewogen gemiddelde over alle 3 buys

### Scenario 3: Bot restart — events gedeeltelijk verloren
- Trade voor restart: `dca_buys=3, dca_events=[{level:1}, {level:2}, {level:3}]`
- Na restart: `dca_buys=3, dca_events=[{level:1}]` (2 events verloren bij serialize/deserialize fout)
- Correct gedrag: `dca_buys` moet teruggebracht worden naar 1 MAAR
  **de bot mag NIET opnieuw DCA triggeren op level 2 en 3** — die zijn al uitgevoerd,
  ook al ontbreken de events.
- Hoe lost jouw design dit op zonder dat je DCA history helemaal kwijtraakt?

### Scenario 4: Cascading DCA preventie
- Trade: `buy_price=1.20, last_dca_price=1.20, dca_buys=0`
- Bot voert DCA uit op 1.17 → `last_dca_price=1.17, dca_buys=1`
- Marktprijs zakt verder naar 1.16 (kleine extra daling)
- Verwacht: GEEN tweede DCA — prijs moet naar `1.17 * (1 - 0.025) = 1.141` voor level 2
- Jouw implementatie moet dit deterministisch voorkomen

### Scenario 5: Sync na herstart met inflated dca_buys
- Trade in bestand: `dca_buys=17, dca_events=[]` (FIX #004 scenario)
- Bitvavo balance: correct bedrag gesynced
- Verwacht: `dca_buys=0` (want geen events = geen bot DCAs)
- Maar: als er wel 17 DCAs zijn (events verloren: vollege order history heeft 17+ buys),
  hoe detecteer je het verschil?

---

## Huidige code om te analyseren

Relevante bestanden (in volgorde van prioriteit):
1. `modules/trading_dca.py` — DCA uitvoering (~830 regels)
2. `bot/sync_engine.py` — Cost basis sync en herberekening
3. `modules/sync_validator.py` — Positie sync bij restart
4. `modules/trade_store.py` — Trade state validatie
5. `modules/cost_basis.py` — FIFO cost basis berekening
6. `trailing_bot.py` — Guards (GUARD 1, 4, 5) in `validate_and_repair_trades()`

---

## Output die ik verwacht

1. **Grondige analyse** van de root causes — waarom blijven deze bugs terugkomen?
   Is het een architectureel probleem of een implementatieprobleem?

2. **Één coherent ontwerp** (nieuw of herstel) met:
   - Data model: welke velden, wat is de single source of truth?
   - Invarianten: welke constraints zijn altijd waar?
   - Update protocol: in welke volgorde worden velden bijgewerkt, atomisch?
   - Sync protocol: hoe worden handmatige buys gedetecteerd en verwerkt?
   - Restart recovery: hoe herstel je correct vanuit disk zonder foute DCA's te triggeren?

3. **Werkende Python code** voor alle 5 scenario's

4. **Unit tests** die de invarianten afdwingen:
   - `dca_buys == len(dca_events)` is altijd waar
   - Handmatige koop wordt correct opgepikt
   - Cascading DCA is onmogelijk
   - Restart herstelt correct

5. **Migratiestrategie** voor bestaande open trades

---

## Extra context

- De bot draait 24/7, ook als ik slaap
- Ik doe gemiddeld 1-2 handmatige DCAs per week
- Max DCA per positie: 5-17 niveaus (configureerbaar, `DCA_MAX_BUYS=17`)
- DCA bedragen: €30-€60 per level, met 0.9x size multiplier
- Drop percentage: 2.0%-2.5% per level (stijgend met `step_multiplier=1.0`)
- Tot nu toe: NEAR-EUR, ALGO-EUR, XRP-EUR, AVAX-EUR als open posities
- Bitvavo API geeft alle order history terug (paginering, max 500 per call)

Wees niet bang om het heilige huis af te breken als het niet werkt.
Liever een nieuw systeem dat wel werkt dan het bestaande blijven lappen.
