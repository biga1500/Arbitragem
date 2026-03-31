"""
Execução de arbitragem entre DEXes BSC (PancakeSwap, Biswap) e Coinbase (CEX).
Fluxo BSC-BSC : USDT → WETH no DEX barato → WETH → USDT no DEX caro.
Fluxo BSC-CEX : compra no DEX on-chain, vende na Coinbase (ou vice-versa).
"""

import os
import time
import uuid
import requests
import hmac
import hashlib
from dataclasses import dataclass

from web3 import Web3
from dotenv import load_dotenv

try:
    from web3.middleware import ExtraDataToPOAMiddleware as _POAMiddleware
except ImportError:
    from web3.middleware import geth_poa_middleware as _POAMiddleware

load_dotenv()

PRIVATE_KEY       = os.getenv("PRIVATE_KEY", "")
BSC_RPC           = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
SLIPPAGE_PCT      = float(os.getenv("SLIPPAGE_PCT", "0.5"))
GAS_LIMIT         = int(os.getenv("GAS_LIMIT", "250000"))
DEADLINE_SEC      = 120
COINBASE_API_KEY  = os.getenv("COINBASE_API_KEY", "")
COINBASE_API_SEC  = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

# Contratos BSC
PANCAKE_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
BISWAP_ROUTER  = "0x3a6d8cA21D1CF76F653A67577FA0D27453350dD8"
BSC_WETH       = "0x2170Ed0880ac9A755fd29B2688956BD959F933F8"
BSC_USDT       = "0x55d398326f99059fF775485246999027B3197955"

ROUTERS = {
    "PancakeSwap": PANCAKE_ROUTER,
    "Biswap":      BISWAP_ROUTER,
}

ROUTER_ABI = [
    {"name": "swapExactTokensForTokens", "type": "function", "inputs": [
        {"name": "amountIn",     "type": "uint256"},
        {"name": "amountOutMin", "type": "uint256"},
        {"name": "path",         "type": "address[]"},
        {"name": "to",           "type": "address"},
        {"name": "deadline",     "type": "uint256"},
    ], "outputs": [{"name": "amounts", "type": "uint256[]"}]},
    {"name": "getAmountsOut", "type": "function", "inputs": [
        {"name": "amountIn", "type": "uint256"},
        {"name": "path",     "type": "address[]"},
    ], "outputs": [{"name": "amounts", "type": "uint256[]"}]},
]

ERC20_ABI = [
    {"name": "approve",   "type": "function", "inputs": [
        {"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}
    ], "outputs": [{"name": "", "type": "bool"}]},
    {"name": "allowance", "type": "function", "inputs": [
        {"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}
    ], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "balanceOf", "type": "function", "inputs": [
        {"name": "account", "type": "address"}
    ], "outputs": [{"name": "", "type": "uint256"}]},
]


@dataclass
class TradeResult:
    step: str         # "BUY" ou "SELL"
    exchange: str
    success: bool
    tx_hash: str | None
    amount_in: float
    amount_out: float
    token_in: str
    token_out: str
    error: str | None = None

    def __str__(self):
        if self.success:
            return (f"[{self.exchange}] {self.step} OK | "
                    f"{self.amount_in:.6f} {self.token_in} -> {self.amount_out:.6f} {self.token_out} | "
                    f"TX: {self.tx_hash}")
        return f"[{self.exchange}] {self.step} FALHOU: {self.error}"


def _w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(_POAMiddleware, layer=0)
    return w3


def _ensure_approval(w3, token_addr, spender, amount, wallet, pk):
    token     = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    allowance = token.functions.allowance(wallet, Web3.to_checksum_address(spender)).call()
    if allowance >= amount:
        return
    print(f"  Aprovando {token_addr[:10]}... para {spender[:10]}...")
    tx = token.functions.approve(
        Web3.to_checksum_address(spender), 2**256 - 1
    ).build_transaction({
        "from": wallet, "nonce": w3.eth.get_transaction_count(wallet),
        "gas": 60000, "gasPrice": w3.eth.gas_price,
    })
    signed = w3.eth.account.sign_transaction(tx, pk)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))


def _swap(w3, router_addr, amount_in, path, wallet, pk) -> tuple[bool, str, int]:
    """Executa um swap. Retorna (sucesso, tx_hash, amount_out)."""
    router      = w3.eth.contract(address=Web3.to_checksum_address(router_addr), abi=ROUTER_ABI)
    amounts_out = router.functions.getAmountsOut(amount_in, path).call()
    amount_min  = int(amounts_out[-1] * (1 - SLIPPAGE_PCT / 100))

    tx = router.functions.swapExactTokensForTokens(
        amount_in, amount_min, path, wallet, int(time.time()) + DEADLINE_SEC
    ).build_transaction({
        "from": wallet, "nonce": w3.eth.get_transaction_count(wallet),
        "gas": GAS_LIMIT, "gasPrice": w3.eth.gas_price,
    })
    signed  = w3.eth.account.sign_transaction(tx, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    success = receipt["status"] == 1
    return success, tx_hash.hex(), amounts_out[-1]


def _coinbase_client():
    from coinbase.rest import RESTClient
    return RESTClient(
        api_key=COINBASE_API_KEY,
        api_secret=os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n"),
    )


def _coinbase_order(side: str, amount_usd: float, eth_price: float = 2000.0) -> TradeResult:
    """
    Executa ordem a mercado ETH-USDT na Coinbase Advanced Trade.
    side: 'BUY' (gasta USDT, recebe ETH) ou 'SELL' (gasta ETH, recebe USDT)
    """
    if not COINBASE_API_KEY or not COINBASE_API_SEC:
        return TradeResult(side, "Coinbase", False, None, amount_usd, 0,
                           "USDT", "ETH", "COINBASE_API_KEY nao configurada no .env")
    try:
        client   = _coinbase_client()
        order_id = str(uuid.uuid4())

        if side == "BUY":
            # Compra ETH gastando USDT (quote_size = valor em USDT)
            resp = client.market_order_buy(
                client_order_id=order_id,
                product_id="ETH-USDT",
                quote_size=str(round(amount_usd, 2)),
            )
        else:
            # Vende ETH recebendo USDT (base_size = quantidade de ETH)
            eth_qty = round(amount_usd / eth_price, 6)
            resp = client.market_order_sell(
                client_order_id=order_id,
                product_id="ETH-USDT",
                base_size=str(eth_qty),
            )

        success = resp.get("success", False)
        order   = resp.get("success_response", {})
        return TradeResult(
            step=side, exchange="Coinbase", success=success,
            tx_hash=order.get("order_id"),
            amount_in=amount_usd, amount_out=0,
            token_in="USDT", token_out="ETH" if side == "BUY" else "USDT",
            error=None if success else str(resp.get("error_response", resp)),
        )
    except Exception as e:
        return TradeResult(side, "Coinbase", False, None, amount_usd, 0,
                           "USDT", "ETH", str(e))


def execute_arbitrage(
    buy_exchange: str,
    sell_exchange: str,
    trade_amount_usd: float,
    pk: str,
) -> tuple[TradeResult, TradeResult]:
    """
    Executa arbitragem entre dois mercados.
    Suporta: DEX-DEX (BSC), DEX-CEX ou CEX-DEX (Coinbase).
    """
    # Coinbase como vendedor (compra no DEX, vende na Coinbase)
    if sell_exchange == "Coinbase":
        w3     = _w3()
        wallet = w3.eth.account.from_key(pk).address
        usdt_in   = int(trade_amount_usd * 1e18)
        path_buy  = [Web3.to_checksum_address(BSC_USDT), Web3.to_checksum_address(BSC_WETH)]
        _ensure_approval(w3, BSC_USDT, ROUTERS[buy_exchange], usdt_in, wallet, pk)
        ok, tx1, weth_received = _swap(w3, ROUTERS[buy_exchange], usdt_in, path_buy, wallet, pk)
        buy_result = TradeResult("BUY", buy_exchange, ok, tx1,
                                 trade_amount_usd, weth_received / 1e18, "USDT", "WETH",
                                 None if ok else "Revertida")
        if not ok:
            return buy_result, TradeResult("SELL", "Coinbase", False, None, 0, 0, "ETH", "USDC", "Passo 1 falhou")
        sell_result = _coinbase_order("SELL", weth_received / 1e18)
        return buy_result, sell_result

    # Coinbase como comprador (compra na Coinbase, vende no DEX)
    if buy_exchange == "Coinbase":
        buy_result  = _coinbase_order("BUY", trade_amount_usd)
        if not buy_result.success:
            return buy_result, TradeResult("SELL", sell_exchange, False, None, 0, 0, "WETH", "USDT", "Passo 1 falhou")
        w3     = _w3()
        wallet = w3.eth.account.from_key(pk).address
        weth_token = w3.eth.contract(address=Web3.to_checksum_address(BSC_WETH), abi=ERC20_ABI)
        weth_bal   = weth_token.functions.balanceOf(wallet).call()
        path_sell  = [Web3.to_checksum_address(BSC_WETH), Web3.to_checksum_address(BSC_USDT)]
        _ensure_approval(w3, BSC_WETH, ROUTERS[sell_exchange], weth_bal, wallet, pk)
        ok, tx2, usdt_received = _swap(w3, ROUTERS[sell_exchange], weth_bal, path_sell, wallet, pk)
        sell_result = TradeResult("SELL", sell_exchange, ok, tx2,
                                  weth_bal / 1e18, usdt_received / 1e18, "WETH", "USDT",
                                  None if ok else "Revertida")
        return buy_result, sell_result

    # DEX-DEX (BSC apenas)
    w3     = _w3()
    wallet = w3.eth.account.from_key(pk).address

    buy_router  = ROUTERS[buy_exchange]
    sell_router = ROUTERS[sell_exchange]

    usdt_in = int(trade_amount_usd * 1e18)
    path_buy  = [Web3.to_checksum_address(BSC_USDT), Web3.to_checksum_address(BSC_WETH)]
    path_sell = [Web3.to_checksum_address(BSC_WETH), Web3.to_checksum_address(BSC_USDT)]

    # ── Passo 1: USDT → WETH no DEX barato ──────────────────────────────────
    try:
        _ensure_approval(w3, BSC_USDT, buy_router, usdt_in, wallet, pk)
        ok, tx1, weth_received = _swap(w3, buy_router, usdt_in, path_buy, wallet, pk)

        buy_result = TradeResult(
            step="BUY", exchange=buy_exchange, success=ok, tx_hash=tx1,
            amount_in=trade_amount_usd, amount_out=weth_received / 1e18,
            token_in="USDT", token_out="WETH",
            error=None if ok else "Transacao revertida (slippage)"
        )
    except Exception as e:
        return (
            TradeResult("BUY", buy_exchange, False, None, trade_amount_usd, 0, "USDT", "WETH", str(e)),
            TradeResult("SELL", sell_exchange, False, None, 0, 0, "WETH", "USDT", "Passo 1 falhou"),
        )

    if not buy_result.success:
        return buy_result, TradeResult("SELL", sell_exchange, False, None, 0, 0, "WETH", "USDT", "Passo 1 falhou")

    # ── Passo 2: WETH → USDT no DEX caro ────────────────────────────────────
    try:
        weth_token = w3.eth.contract(address=Web3.to_checksum_address(BSC_WETH), abi=ERC20_ABI)
        weth_bal   = weth_token.functions.balanceOf(wallet).call()

        _ensure_approval(w3, BSC_WETH, sell_router, weth_bal, wallet, pk)
        ok, tx2, usdt_received = _swap(w3, sell_router, weth_bal, path_sell, wallet, pk)

        sell_result = TradeResult(
            step="SELL", exchange=sell_exchange, success=ok, tx_hash=tx2,
            amount_in=weth_bal / 1e18, amount_out=usdt_received / 1e18,
            token_in="WETH", token_out="USDT",
            error=None if ok else "Transacao revertida (slippage)"
        )
    except Exception as e:
        sell_result = TradeResult("SELL", sell_exchange, False, None,
                                  weth_received / 1e18, 0, "WETH", "USDT", str(e))

    return buy_result, sell_result
