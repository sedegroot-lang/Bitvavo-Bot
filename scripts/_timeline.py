"""Generate portfolio timeline with monthly deposits + expected returns."""

start_balance = 376  # Current portfolio EUR
monthly_deposit = 100  # EUR per month

# Three scenarios based on REAL data (without flood guard, which is now disabled)
# Nov: -242, Dec: +43, Jan: +556, Feb: +257 → avg +153/month on ~400 portfolio
# That's roughly +38% return/month — but Jan was exceptional
# Conservative: use worst month without flood (Dec: +43 on ~400 = ~1%/month) 
# Moderate: use average without flood (+123/month on ~400 avg = ~3%/month)
# Optimistic: use average of Dec+Feb without flood ((43+257)/2 = 150 on ~450 = ~3.5%/month)
# Note: returns scale with portfolio size

scenarios = {
    "Pessimistisch (0%)": 0.00,      # Only deposits, no bot profit
    "Conservatief (1%/mnd)": 0.01,    # ~Dec level performance
    "Realistisch (2%/mnd)": 0.02,     # Between Dec and avg
    "Optimistisch (3%/mnd)": 0.03,    # Avg without flood guard
}

milestones = list(range(500, 5100, 100))

print("=" * 80)
print("PORTFOLIO TIMELINE — Start: EUR 376 + EUR 100/maand storting")
print("=" * 80)
print()
print("Scenario's gebaseerd op historische data ZONDER flood guard (nu uitgeschakeld):")
print("  Pessimistisch: 0% rendement (alleen stortingen)")
print("  Conservatief:  1%/maand (~Dec 2025 niveau)")
print("  Realistisch:   2%/maand (gemiddeld aangepast)")
print("  Optimistisch:  3%/maand (~gemiddelde zonder flood guard)")
print()

# Calculate for each scenario
results = {}
for name, rate in scenarios.items():
    balance = start_balance
    month = 0
    timeline = {}
    
    while balance < max(milestones) and month < 60:  # max 5 jaar
        month += 1
        # Profit on current balance
        profit = balance * rate
        # Add deposit
        balance += monthly_deposit + profit
        
        # Check milestones
        for ms in milestones:
            if ms not in timeline and balance >= ms:
                timeline[ms] = month
    
    results[name] = timeline

# Print timeline table
print(f"{'Milestone':>12}", end="")
for name in scenarios:
    short = name.split("(")[0].strip()
    print(f" | {short:>16}", end="")
print(" |")
print("-" * 12, end="")
for _ in scenarios:
    print("-|-" + "-" * 16, end="")
print("-|")

months_nl = ["", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]

for ms in milestones:
    print(f"  EUR {ms:>5,}", end="")
    for name in scenarios:
        m = results[name].get(ms)
        if m is not None:
            # Convert month number to actual date
            start_month = 3  # March 2026
            start_year = 2026
            actual_month = (start_month + m - 1) % 12 + 1
            actual_year = start_year + (start_month + m - 1) // 12
            date_str = f"{months_nl[actual_month]} {actual_year}"
            print(f" | {m:>2} mnd ({date_str:>8})", end="")
        else:
            print(f" | {'> 5 jaar':>16}", end="")
    print(" |")

# Key milestone summary
print()
print("=" * 80)
print("BELANGRIJKE MIJLPALEN")
print("=" * 80)
key_milestones = [500, 800, 1000, 1500, 2000, 3000, 5000]
for ms in key_milestones:
    print(f"\n  EUR {ms:,}:")
    for name in scenarios:
        m = results[name].get(ms)
        if m:
            start_month = 3
            start_year = 2026
            actual_month = (start_month + m - 1) % 12 + 1
            actual_year = start_year + (start_month + m - 1) // 12
            total_deposited = start_balance + m * monthly_deposit
            total_profit = ms - total_deposited
            profit_pct = total_profit / total_deposited * 100
            date_str = f"{months_nl[actual_month]} {actual_year}"
            print(f"    {name:<30} {m:>2} maanden ({date_str}) — gestort: EUR {total_deposited:,.0f}, winst: EUR {total_profit:+,.0f} ({profit_pct:+.1f}%)")
        else:
            print(f"    {name:<30} > 5 jaar")

# Cumulative deposits vs portfolio value over time
print()
print("=" * 80)  
print("GROEI OVER TIJD (Realistisch scenario: 2%/maand)")
print("=" * 80)
rate = 0.02
balance = start_balance
print(f"\n  {'Maand':>6} {'Datum':>10} {'Gestort':>10} {'Portfolio':>10} {'Winst':>10} {'Rendement':>10}")
print(f"  {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
print(f"  {'Start':>6} {'Mrt 2026':>10} {'EUR 376':>10} {'EUR 376':>10} {'EUR 0':>10} {'0.0%':>10}")

for month in range(1, 49):
    profit = balance * rate
    balance += monthly_deposit + profit
    total_deposited = start_balance + month * monthly_deposit
    total_profit = balance - total_deposited
    roi = total_profit / total_deposited * 100
    
    start_month = 3
    start_year = 2026
    actual_month = (start_month + month - 1) % 12 + 1
    actual_year = start_year + (start_month + month - 1) // 12
    date_str = f"{months_nl[actual_month]} {actual_year}"
    
    if month <= 12 or month % 6 == 0 or balance >= 5000:
        print(f"  {month:>6} {date_str:>10} EUR {total_deposited:>6,.0f} EUR {balance:>6,.0f} EUR {total_profit:>+6,.0f} {roi:>+9.1f}%")
    
    if balance >= 5000:
        print(f"\n  >>> EUR 5.000 bereikt in maand {month}! <<<")
        break
