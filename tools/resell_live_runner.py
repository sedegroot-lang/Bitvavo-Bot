import csv, time, os, argparse, sys

# Make sure project root is on sys.path so local `modules` package can be imported
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.logging_utils import log, file_lock

IN = 'tools/top10_resell_recommendations.csv'
OUT = 'tools/resell_live_log.csv'
RATE_DELAY = 2.0

parser = argparse.ArgumentParser()
parser.add_argument('--top', type=int, default=0, help='Limit to top N entries (0 = all)')
parser.add_argument('--dry-run', action='store_true', help='Do not send live orders, only log intended orders')
parser.add_argument('--operator-id', type=str, default=None, help='Operator ID to include in order body (overrides BITVAVO_OPERATOR_ID env)')
args = parser.parse_args()

# Load API keys from environment or from .env file if present
API_KEY = os.environ.get('BITVAVO_API_KEY')
API_SECRET = os.environ.get('BITVAVO_API_SECRET')
API_OPERATOR = os.environ.get('BITVAVO_OPERATOR_ID')
if not API_KEY or not API_SECRET:
    # Try to read .env in workspace root
    envpath = os.path.join(os.getcwd(), '.env')
    if os.path.exists(envpath):
        with open(envpath, 'r', encoding='utf-8') as ef:
            for line in ef:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k,v = line.split('=',1)
                k=k.strip(); v=v.strip()
                if k == 'BITVAVO_API_KEY' and not API_KEY:
                    API_KEY = v
                if k == 'BITVAVO_API_SECRET' and not API_SECRET:
                    API_SECRET = v
                if k == 'BITVAVO_OPERATOR_ID' and not API_OPERATOR:
                    API_OPERATOR = v

if not API_KEY or not API_SECRET:
    print('API_KEY/API_SECRET not found in env or .env - aborting live run')
    raise SystemExit(1)

# Import Bitvavo client and create a fresh instance
from python_bitvavo_api.bitvavo import Bitvavo
bitvavo = Bitvavo({"APIKEY": API_KEY, "APISECRET": API_SECRET})

rows = []
with open(IN, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        rows.append(row)

if args.top and args.top > 0:
    rows = rows[:args.top]

os.makedirs('tools', exist_ok=True)
# Only write header if file does not exist
if not os.path.exists(OUT):
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['ts','market','amount','price','status','response','dry_run'])

for r in rows:
    market = r.get('market')
    amount = r.get('amount')
    price = r.get('planned_price')
    try:
        amount_f = float(amount)
        price_f = float(price)
    except Exception:
        amount_f = None
        price_f = None

    print(f'Placing {market} amount={amount_f} price={price_f}')
    if not amount_f or not price_f:
        print('Skipping due to invalid amount/price')
        continue

    # Build order body and include operatorId if provided
    body = { 'amount': str(amount_f), 'price': str(price_f) }
    operator_id = args.operator_id if args.operator_id else API_OPERATOR
    if operator_id:
        body['operatorId'] = str(operator_id)

    if args.dry_run:
        status = 'dry-run'
        resp = { 'note': 'dry-run, not placed', 'body': body }
    else:
        try:
            order = bitvavo.placeOrder(market, 'sell', 'limit', body)
            status = 'ok'
            resp = order
        except Exception as e:
            status = 'error'
            resp = str(e)

    ts = time.time()
    with file_lock:
        with open(OUT, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow([ts, market, amount_f, price_f, status, str(resp), str(args.dry_run)])

    if status == 'error':
        print('Error encountered, stopping live run.')
        break

    time.sleep(RATE_DELAY)

print('Live run complete. Log:', OUT)
