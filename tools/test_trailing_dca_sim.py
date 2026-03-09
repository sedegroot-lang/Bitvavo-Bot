# Quick simulation tests for trailing + DCA interaction
from datetime import datetime
import time
from trailing_bot import calculate_stop_levels

# Scenario helpers

def sim_calc(buy, high, cp):
    stop, trailing, hard, trend = calculate_stop_levels('BTC-EUR', buy, high)
    print(f"buy={buy}, high={high}, cp={cp} -> stop={stop:.6f}, trailing={trailing:.6f}, hard={hard:.6f}, trend={trend:.6f}")

print('Scenario A: no DCA, high above activation')
sim_calc(100.0, 105.0, 102.0)

print('\nScenario B: DCA reduces average buy (simulate by lowering buy), trailing should use stored hw when activated')
# We call calculate_stop_levels directly; test for expected numeric values (note: calculate_stop_levels doesn't accept trade dict here)
sim_calc(90.0, 110.0, 95.0)

print('\nScenario C: activation near boundary')
sim_calc(100.0, 102.0, 101.0)
