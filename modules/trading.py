import asyncio
import json
import os
import threading
import time
from typing import Any

from dotenv import load_dotenv

try:
	from python_bitvavo_api.bitvavo import Bitvavo
except Exception:  # pragma: no cover - optional dependency
	Bitvavo = None

from modules.config import CONFIG, load_config
from modules.logging_utils import log, file_lock, locked_write_json


load_dotenv()


def _init_bitvavo() -> Any:
	"""Instantiate Bitvavo with environment/config fallbacks."""
	api_key = os.getenv("BITVAVO_API_KEY") or CONFIG.get("API_KEY") or CONFIG.get("BITVAVO_API_KEY")
	api_secret = os.getenv("BITVAVO_API_SECRET") or CONFIG.get("API_SECRET") or CONFIG.get("BITVAVO_API_SECRET")
	operator_id = os.getenv("BITVAVO_OPERATOR_ID") or CONFIG.get("BITVAVO_OPERATOR_ID") or CONFIG.get("OPERATOR_ID")
	try:
		if Bitvavo is None:
			raise RuntimeError("python-bitvavo-api pakket ontbreekt.")
		if not api_key or not api_secret:
			raise RuntimeError("Bitvavo credentials ontbreken (BITVAVO_API_KEY/SECRET).")
		if not operator_id:
			raise RuntimeError("Bitvavo operator ID ontbreekt (BITVAVO_OPERATOR_ID).")
		client_config = {
			"APIKEY": api_key,
			"APISECRET": api_secret,
			"OPERATORID": operator_id,
		}
		return Bitvavo(client_config)
	except Exception as exc:
		log(f"Bitvavo initialisatie mislukt: {exc}", level='error')

		class _DeadClient:
			def __getattr__(self, _name):
				def _noop(*_args, **_kwargs):
					raise RuntimeError('Bitvavo client niet geconfigureerd; stel API keys in.')

				return _noop

		return _DeadClient()


bitvavo = _init_bitvavo()

# File locking bij alle schrijfoperaties

def get_config_param(key, default=None):
	config = load_config()
	return config.get(key, default)

TRADE_LOG = get_config_param("TRADE_LOG", os.path.join("data", "trade_log.json"))
ARCHIVE_FILE = get_config_param("ARCHIVE_FILE", os.path.join("data", "trade_archive.json"))
MAX_CLOSED = get_config_param("MAX_CLOSED", 200)

# Async marktdata en orderboek-caching
orderbook_cache = {}
async def fetch_orderbook(market, depth=5):
	if market in orderbook_cache:
		return orderbook_cache[market]
	book = await asyncio.to_thread(bitvavo.book, market, {'depth': depth})
	orderbook_cache[market] = book
	return book

async def fetch_all_orderbooks(markets, depth=5):
	tasks = [fetch_orderbook(m, depth) for m in markets]
	return await asyncio.gather(*tasks)

def save_trades(open_trades, closed_trades, market_profits):
	"""
	Slaat open, gesloten trades en marktwinsten veilig op in TRADE_LOG met file locking.
	"""
	data = {"open": open_trades, "closed": closed_trades, "profits": market_profits}
	try:
		locked_write_json(TRADE_LOG, data, indent=2)
	except Exception as e:
		log(f"Kon {TRADE_LOG} niet opslaan: {e}", level='error')

def cleanup_trades(closed_trades):
	"""
	Archiveert oude trades naar ARCHIVE_FILE en houdt alleen de laatste MAX_CLOSED in memory.
	Thread-safe: alle operaties binnen file_lock om race conditions te voorkomen.
	"""
	if len(closed_trades) > MAX_CLOSED:
		old = closed_trades[:-MAX_CLOSED]
		closed_trades = closed_trades[-MAX_CLOSED:]
		with file_lock:
			# Lees archive binnen lock
			if os.path.exists(ARCHIVE_FILE):
				with open(ARCHIVE_FILE, encoding='utf-8') as f:
					archive = json.load(f)
			else:
				archive = []
			# Extend ook binnen lock (fix race condition)
			archive.extend(old)
			# Schrijf binnen lock
			try:
				with open(ARCHIVE_FILE, 'w', encoding='utf-8') as f:
					json.dump(archive, f, indent=2)
			except Exception as e:
				log(f"Kon {ARCHIVE_FILE} niet bijwerken: {e}", level='error')
		log(f"🗑️ {len(old)} oude trades verplaatst naar {ARCHIVE_FILE}")

# Voorbeeld: schrijf dynamische config updates met file_lock
def save_config(config):
	"""
	Slaat de config veilig op naar bot_config.json met file locking.
	"""
	try:
		locked_write_json(os.path.join("config", "bot_config.json"), config, indent=2)
		log("Config succesvol opgeslagen.", level='debug')
	except Exception as e:
		log(f"Kon bot_config.json niet opslaan: {e}", level='error')

# ...hier komen meer trading functies met file locking...
