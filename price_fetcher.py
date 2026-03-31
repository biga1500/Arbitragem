"""
Consulta de preços do ETH/USDT na BSC: PancakeSwap e Biswap.
Usa DexScreener — sem dependência de web3.
"""

import requests

DEXSCREENER_URL = (
    "https://api.dexscreener.com/latest/dex/tokens"
    "/0x2170Ed0880ac9A755fd29B2688956BD959F933F8"  # WETH na BSC
)

def _get_bsc_dex_price(dex_id: str) -> float | None:
    """Busca o preço WETH/USDT no DEX especificado via DexScreener."""
    try:
        response = requests.get(DEXSCREENER_URL, timeout=10)
        response.raise_for_status()
        pairs = response.json().get("pairs", [])

        candidates = [
            p for p in pairs
            if p.get("chainId") == "bsc"
            and dex_id in p.get("dexId", "").lower()
            and p.get("quoteToken", {}).get("symbol", "").upper() in ("USDT", "BUSD", "USDC")
            and p.get("baseToken", {}).get("symbol", "").upper() in ("ETH", "WETH")
        ]

        if not candidates:
            print(f"[{dex_id}] Nenhum par encontrado.")
            return None

        best = max(candidates, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
        return float(best["priceUsd"])
    except Exception as e:
        print(f"[{dex_id}] Erro: {e}")
        return None


def get_pancakeswap_price() -> float | None:
    return _get_bsc_dex_price("pancakeswap")

def get_biswap_price() -> float | None:
    return _get_bsc_dex_price("biswap")

def get_apeswap_price() -> float | None:
    return _get_bsc_dex_price("apeswap")

def get_nomiswap_price() -> float | None:
    return _get_bsc_dex_price("nomiswap")


def fetch_all_prices(*_, **__) -> dict:
    """Retorna preços do ETH em todos os DEXes monitorados na BSC."""
    # Faz uma única chamada à API e distribui para todos os DEXes
    try:
        import requests
        response = requests.get(DEXSCREENER_URL, timeout=10)
        response.raise_for_status()
        pairs = response.json().get("pairs", [])
    except Exception as e:
        print(f"[DexScreener] Erro: {e}")
        pairs = []

    dexes = {
        "PancakeSwap": "pancakeswap",
        "Biswap":      "biswap",
    }

    prices = {}
    for name, dex_id in dexes.items():
        candidates = [
            p for p in pairs
            if p.get("chainId") == "bsc"
            and dex_id in p.get("dexId", "").lower()
            and p.get("quoteToken", {}).get("symbol", "").upper() in ("USDT", "BUSD", "USDC")
            and p.get("baseToken", {}).get("symbol", "").upper() in ("ETH", "WETH")
        ]
        if candidates:
            best = max(candidates, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
            prices[name] = float(best["priceUsd"])
        else:
            prices[name] = None

    # Coinbase via API REST pública
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/ETH-USD/spot", timeout=10)
        r.raise_for_status()
        prices["Coinbase"] = float(r.json()["data"]["amount"])
    except Exception as e:
        print(f"[Coinbase] Erro: {e}")
        prices["Coinbase"] = None

    return prices
