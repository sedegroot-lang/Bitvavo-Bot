"""
Crypto Logo Mapper - Dynamic Cryptocurrency Logo URLs via CoinGecko API

Maps Bitvavo market pairs (e.g., BTC-EUR, ETH-EUR) to CoinGecko coin IDs
and provides CDN URLs for high-quality logos.

Usage:
    from crypto_logo_mapper import get_crypto_logo_url
    
    logo_url = get_crypto_logo_url("BTC-EUR")  # Bitcoin logo
    logo_url = get_crypto_logo_url("ETH-EUR")  # Ethereum logo
"""

# CoinGecko API coin ID mapping for popular cryptocurrencies
# Format: "SYMBOL": "coingecko_id"
CRYPTO_COINGECKO_MAP = {
    # Top 20 by market cap
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "USDC": "usd-coin",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "TON": "the-open-network",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "SHIB": "shiba-inu",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ATOM": "cosmos",
    
    # Additional popular coins on Bitvavo
    "ALGO": "algorand",
    "AAVE": "aave",
    "APE": "apecoin",
    "ARB": "arbitrum",
    "BAT": "basic-attention-token",
    "CELO": "celo",
    "CHZ": "chiliz",
    "COMP": "compound-governance-token",
    "CRV": "curve-dao-token",
    "DAI": "dai",
    "ENS": "ethereum-name-service",
    "EOS": "eos",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "FTM": "fantom",
    "GRT": "the-graph",
    "HBAR": "hedera-hashgraph",
    "ICP": "internet-computer",
    "IMX": "immutable-x",
    "KAVA": "kava",
    "KNC": "kyber-network-crystal",
    "LDO": "lido-dao",
    "MANA": "decentraland",
    "MKR": "maker",
    "NEAR": "near",
    "OP": "optimism",
    "PAXG": "pax-gold",
    "PEPE": "pepe",
    "SAND": "the-sandbox",
    "SNX": "synthetix-network-token",
    "STORJ": "storj",
    "SUSHI": "sushi",
    "UMA": "uma",
    "VET": "vechain",
    "XLM": "stellar",
    "XTZ": "tezos",
    "YFI": "yearn-finance",
    "ZEC": "zcash",
    "ZRX": "0x",
    "1INCH": "1inch",
    
    # Meme coins
    "FLOKI": "floki",
    "BONK": "bonk",
    "MOODENG": "moo-deng",  # If available on CoinGecko
    
    # Stablecoins
    "BUSD": "binance-usd",
    "TUSD": "true-usd",
    
    # DeFi tokens
    "CRO": "crypto-com-chain",
    "CAKE": "pancakeswap-token",
    "RUNE": "thorchain",
    
    # Layer 2 / Scaling
    "MATIC": "matic-network",
    "LRC": "loopring",
    
    # Other
    "THETA": "theta-token",
    "EGLD": "elrond-erd-2",
    "AXS": "axie-infinity",
    "GALA": "gala",
    "APT": "aptos",
    "SUI": "sui",
    
    # Additional Bitvavo coins
    "FET": "fetch-ai",
    "DYDX": "dydx",
    "ENA": "ethena",
    "COTI": "coti",
}

# Fallback SVG data URI for unmapped coins (inline, no external request)
def FALLBACK_LOGO_URL(symbol):
    """Generate inline SVG data URI for fallback logos."""
    letter = symbol[0] if symbol else "?"
    return f"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'><rect width='64' height='64' fill='%233B82F6'/><text x='50%' y='50%' text-anchor='middle' dy='.3em' font-size='32' fill='white' font-family='Arial'>{letter}</text></svg>"


def extract_symbol_from_market(market: str) -> str:
    """
    Extract base currency symbol from market pair.
    
    Examples:
        BTC-EUR -> BTC
        ETH-EUR -> ETH
        DOGE-EUR -> DOGE
    """
    if not market or "-" not in market:
        return market.upper() if market else "UNKNOWN"
    
    return market.split("-")[0].upper()


def get_coingecko_id(symbol: str) -> str | None:
    """
    Get CoinGecko coin ID for a cryptocurrency symbol.
    
    Args:
        symbol: Cryptocurrency symbol (e.g., "BTC", "ETH")
        
    Returns:
        CoinGecko coin ID (e.g., "bitcoin", "ethereum") or None if not found
    """
    return CRYPTO_COINGECKO_MAP.get(symbol.upper())


def get_crypto_logo_url(market: str, size: str = "large", prefer_local: bool = True) -> str:
    """
    Get cryptocurrency logo URL. Checks local icons first, then CoinGecko CDN fallback.
    
    Args:
        market: Market pair (e.g., "BTC-EUR", "ETH-EUR") or symbol (e.g., "BTC")
        size: Image size - "thumb" (32px), "small" (64px), or "large" (200px)
        prefer_local: If True, return local /icons/ path first (default: True)
        
    Returns:
        Local icon path, CoinGecko CDN URL, or SVG fallback
        
    Examples:
        >>> get_crypto_logo_url("BTC-EUR")
        '/icons/btc.png'  # Local icon (200+ coins available)
        
        >>> get_crypto_logo_url("ETH-EUR", prefer_local=False)
        'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
        
        >>> get_crypto_logo_url("UNKNOWN-EUR")
        'data:image/svg+xml,...'  # SVG fallback with "U" letter
    """
    # Extract symbol from market pair
    symbol = extract_symbol_from_market(market)
    
    # Strategy 1: Local icons (fastest, no external dependencies)
    if prefer_local:
        # Return local Flask route - will serve data/icons/{symbol}.png
        # If file doesn't exist, browser will fallback via onerror handler
        return f"/icons/{symbol.lower()}.png"
    
    # Strategy 2: CoinGecko CDN (external dependency)
    coin_id = get_coingecko_id(symbol)
    
    if not coin_id:
        # Return fallback SVG data URI with symbol initial
        return FALLBACK_LOGO_URL(symbol)
    
    # Map coin ID to CoinGecko CDN image ID (hardcoded mapping for top coins)
    # This avoids API calls and uses direct CDN URLs
    IMAGE_ID_MAP = {
        "bitcoin": 1,
        "ethereum": 279,
        "tether": 325,
        "binancecoin": 825,
        "solana": 4128,
        "ripple": 44,
        "usd-coin": 6319,
        "cardano": 975,
        "dogecoin": 5,
        "tron": 1094,
        "the-open-network": 17980,
        "chainlink": 877,
        "avalanche-2": 12559,
        "matic-network": 4713,
        "polkadot": 12171,
        "shiba-inu": 11939,
        "uniswap": 12504,
        "litecoin": 2,
        "bitcoin-cash": 780,
        "cosmos": 6783,
        "algorand": 4030,
        "aave": 12645,
        "apecoin": 24383,
        "arbitrum": 16547,
        "basic-attention-token": 677,
        "celo": 11756,
        "chiliz": 8834,
        "compound-governance-token": 10775,
        "curve-dao-token": 12124,
        "dai": 9956,
        "ethereum-name-service": 19785,
        "eos": 1765,
        "ethereum-classic": 453,
        "filecoin": 12817,
        "fantom": 4001,
        "the-graph": 13397,
        "hedera-hashgraph": 3688,
        "internet-computer": 14495,
        "immutable-x": 17233,
        "kava": 4846,
        "kyber-network-crystal": 14899,
        "lido-dao": 13573,
        "decentraland": 878,
        "maker": 1364,
        "near": 10365,
        "optimism": 11840,
        "pax-gold": 9519,
        "pepe": 29850,
        "the-sandbox": 12129,
        "synthetix-network-token": 5013,
        "storj": 677,
        "sushi": 12271,
        "uma": 10951,
        "vechain": 1063,
        "stellar": 100,
        "tezos": 2011,
        "yearn-finance": 11849,
        "zcash": 486,
        "0x": 863,
        "1inch": 13810,
        "floki": 16746,
        "bonk": 28600,
        "moo-deng": 38913,
        "fetch-ai": 5681,
        "dydx": 11156,
        "ethena": 36345,
        "coti": 3885,
        "aptos": 26455,
        "sui": 26375,
    }
    
    # Get image ID from mapping
    image_id = IMAGE_ID_MAP.get(coin_id, 0)
    
    if image_id == 0:
        # Coin not in hardcoded map - return fallback SVG
        return FALLBACK_LOGO_URL(symbol)
    
    # Construct CoinGecko CDN URL
    # Format: https://assets.coingecko.com/coins/images/{id}/{size}/{coin_id}.png
    return f"https://assets.coingecko.com/coins/images/{image_id}/{size}/{coin_id}.png"


def get_crypto_name(market: str) -> str:
    """
    Get full cryptocurrency name from market pair.
    
    Args:
        market: Market pair (e.g., "BTC-EUR")
        
    Returns:
        Full cryptocurrency name (e.g., "Bitcoin")
        
    Examples:
        >>> get_crypto_name("BTC-EUR")
        'Bitcoin'
        >>> get_crypto_name("ETH-EUR")
        'Ethereum'
    """
    # Extract symbol
    symbol = extract_symbol_from_market(market)
    
    # Name mapping (optional - for display purposes)
    NAME_MAP = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "USDT": "Tether",
        "BNB": "Binance Coin",
        "SOL": "Solana",
        "XRP": "Ripple",
        "USDC": "USD Coin",
        "ADA": "Cardano",
        "DOGE": "Dogecoin",
        "TRX": "Tron",
        "TON": "TON Network",
        "LINK": "Chainlink",
        "AVAX": "Avalanche",
        "MATIC": "Polygon",
        "DOT": "Polkadot",
        "SHIB": "Shiba Inu",
        "UNI": "Uniswap",
        "LTC": "Litecoin",
        "BCH": "Bitcoin Cash",
        "ATOM": "Cosmos",
        "ALGO": "Algorand",
        "AAVE": "Aave",
        "APE": "ApeCoin",
        "ARB": "Arbitrum",
        "PEPE": "Pepe",
        "MOODENG": "Moo Deng",
        "FLOKI": "Floki Inu",
        "BONK": "Bonk",
    }
    
    return NAME_MAP.get(symbol, symbol)


# Export public API
__all__ = [
    "get_crypto_logo_url",
    "get_crypto_name",
    "extract_symbol_from_market",
    "get_coingecko_id",
]
