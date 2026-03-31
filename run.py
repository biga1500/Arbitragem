"""
Ponto de entrada principal.
Fluxo: verifica saldo → bridge para BSC → aguarda chegada → setup gas → monitora.
"""

import os
import time
import requests
from dotenv import load_dotenv
from web3 import Web3
from colorama import init, Fore, Style

try:
    from web3.middleware import ExtraDataToPOAMiddleware as _POAMiddleware
except ImportError:
    from web3.middleware import geth_poa_middleware as _POAMiddleware

load_dotenv()
init(autoreset=True)

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
ETH_RPC     = os.getenv("ETH_RPC_URL", "https://ethereum.publicnode.com")
BSC_RPC     = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")

LIFI_API     = "https://li.quest/v1"
CHAIN_ETH    = 1
CHAIN_BSC    = 56
NATIVE       = "0x0000000000000000000000000000000000000000"
BSC_USDT     = "0x55d398326f99059fF775485246999027B3197955"
BSC_WBNB     = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
ETH_WBTC     = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"  # WBTC (8 decimais)
ETH_USDT     = "0xdAC17F958D2ee523a2206206994597C13D831ec7"  # USDT Ethereum
ETH_GAS_RESERVE = 0.002   # ETH reservado para pagar gas da bridge

ROUTER_ABI = [
    {"name": "swapExactTokensForETH", "type": "function", "inputs": [
        {"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"},
        {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"},
        {"name": "deadline", "type": "uint256"}
    ], "outputs": [{"name": "amounts", "type": "uint256[]"}]},
    {"name": "getAmountsOut", "type": "function", "inputs": [
        {"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}
    ], "outputs": [{"name": "amounts", "type": "uint256[]"}]},
]
ERC20_ABI = [
    {"name": "approve",   "type": "function", "inputs": [
        {"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}
    ], "outputs": [{"name": "", "type": "bool"}]},
    {"name": "balanceOf", "type": "function", "inputs": [
        {"name": "account", "type": "address"}
    ], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "allowance", "type": "function", "inputs": [
        {"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}
    ], "outputs": [{"name": "", "type": "uint256"}]},
]
PANCAKE_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
BNB_RESERVA_USD = 2.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_btc_price() -> float:
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": "BTCUSDT"}, timeout=5)
        return float(r.json()["price"])
    except Exception:
        return 95000.0  # fallback

# ── Web3 helpers ──────────────────────────────────────────────────────────────

def _w3_eth():
    return Web3(Web3.HTTPProvider(ETH_RPC, request_kwargs={"timeout": 15}))

def _w3_bsc():
    w3 = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(_POAMiddleware, layer=0)
    return w3


# ── 1. Verificar saldo ────────────────────────────────────────────────────────

def check_balances(wallet: str) -> dict:
    w3e  = _w3_eth()
    w3b  = _w3_bsc()
    wbtc = w3e.eth.contract(address=Web3.to_checksum_address(ETH_WBTC), abi=ERC20_ABI)
    usdt = w3b.eth.contract(address=Web3.to_checksum_address(BSC_USDT), abi=ERC20_ABI)
    return {
        "eth":      w3e.eth.get_balance(wallet) / 1e18,
        "wbtc":     wbtc.functions.balanceOf(wallet).call() / 1e8,   # WBTC tem 8 decimais
        "bnb":      w3b.eth.get_balance(wallet) / 1e18,
        "bsc_usdt": usdt.functions.balanceOf(wallet).call() / 1e18,
    }


# ── 2. Bridge ETH → USDT na BSC via Li.Fi ────────────────────────────────────

def bridge_to_bsc(wallet: str, amount_eth: float, pk: str,
                  from_token: str = NATIVE, decimals: int = 18, label: str = "ETH") -> str | None:
    amount_wei = int(amount_eth * 10**decimals)
    print(f"\n  Buscando rota de bridge para {amount_eth:.6f} {label} -> USDT na BSC...")
    try:
        resp = requests.get(f"{LIFI_API}/quote", params={
            "fromChain":   CHAIN_ETH,
            "toChain":     CHAIN_BSC,
            "fromToken":   from_token,
            "toToken":     BSC_USDT,
            "fromAmount":  str(amount_wei),
            "fromAddress": wallet,
        }, timeout=15)
        resp.raise_for_status()
        quote = resp.json()
    except Exception as e:
        print(Fore.RED + f"  Erro ao consultar Li.Fi: {e}")
        return None

    tool     = quote.get("toolDetails", {}).get("name", "?")
    est_out  = int(quote.get("estimate", {}).get("toAmount", 0)) / 1e18
    fee_usd  = sum(float(f.get("amountUSD", 0)) for f in quote.get("estimate", {}).get("feeCosts", []))
    est_time = quote.get("estimate", {}).get("executionDuration", 0)

    print(f"\n  Rota     : {tool}")
    print(f"  Envia    : {amount_eth:.6f} {label}")
    print(f"  Recebe   : ~{est_out:.2f} USDT na BSC")
    print(f"  Taxa     : ~${fee_usd:.2f}")
    print(f"  Tempo    : ~{max(1, est_time//60):.0f} min")

    w3e    = _w3_eth()
    tx_raw = quote["transactionRequest"]

    # Se não for ETH nativo, precisa aprovar o spender
    if from_token != NATIVE:
        spender  = tx_raw["to"]
        token_c  = w3e.eth.contract(address=Web3.to_checksum_address(from_token), abi=ERC20_ABI)
        allowance = token_c.functions.allowance(wallet, Web3.to_checksum_address(spender)).call()
        if allowance < amount_wei:
            print(f"  Aprovando {label} para bridge...")
            approve = token_c.functions.approve(
                Web3.to_checksum_address(spender), 2**256 - 1
            ).build_transaction({
                "from": wallet, "nonce": w3e.eth.get_transaction_count(wallet),
                "gas": 60000, "gasPrice": w3e.eth.gas_price,
            })
            signed = w3e.eth.account.sign_transaction(approve, pk)
            w3e.eth.wait_for_transaction_receipt(w3e.eth.send_raw_transaction(signed.raw_transaction))
            print(Fore.GREEN + "  Aprovado." + Style.RESET_ALL)

    def _parse(v):
        return int(v, 16) if isinstance(v, str) and v.startswith("0x") else int(v)

    tx = {
        "from":     wallet,
        "to":       tx_raw["to"],
        "data":     tx_raw["data"],
        "value":    _parse(tx_raw.get("value", "0x0")),
        "gas":      _parse(tx_raw.get("gasLimit", "0x493E0")),
        "gasPrice": _parse(tx_raw.get("gasPrice", str(w3e.eth.gas_price))),
        "nonce":    w3e.eth.get_transaction_count(wallet),
        "chainId":  CHAIN_ETH,
    }

    signed  = w3e.eth.account.sign_transaction(tx, pk)
    tx_hash = w3e.eth.send_raw_transaction(signed.raw_transaction).hex()
    print(Fore.GREEN + f"\n  TX enviada: {tx_hash}")
    print(f"  Acompanhe: https://etherscan.io/tx/{tx_hash}" + Style.RESET_ALL)
    return tx_hash


def wait_bridge(tx_hash: str):
    print("\n  Aguardando confirmacao da bridge", end="", flush=True)
    for _ in range(90):
        try:
            r = requests.get(f"{LIFI_API}/status", params={
                "txHash": tx_hash, "fromChain": CHAIN_ETH, "toChain": CHAIN_BSC,
            }, timeout=10).json()
            if r.get("status") == "DONE":
                amt = int(r.get("receiving", {}).get("amount", 0)) / 1e18
                print(Fore.GREEN + f"\n  Bridge concluida! +{amt:.2f} USDT na BSC" + Style.RESET_ALL)
                return True
            if r.get("status") == "FAILED":
                print(Fore.RED + f"\n  Bridge falhou: {r.get('substatusMessage','')}" + Style.RESET_ALL)
                return False
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(10)
    print(Fore.YELLOW + "\n  Timeout — verifique manualmente." + Style.RESET_ALL)
    return False


# ── 3. Setup BNB para gas via bridge ETH → BNB nativo ────────────────────────
#
# Problema: sem BNB não dá para pagar gas na BSC — nem para comprar BNB.
# Solução: bridge uma pequena quantidade de ETH diretamente como BNB nativo
# via Li.Fi (ETH mainnet → BNB na BSC), sem precisar de gas na BSC.

BNB_MINIMO    = 0.003   # abaixo disso recarrega (~$1.80)
BNB_RECARGA   = 3.0     # troca $3 de USDT por BNB a cada recarga

def _swap_usdt_para_bnb(wallet: str, pk: str, w3b) -> bool:
    """Troca $3 de USDT por BNB na PancakeSwap para recarregar gas."""
    router    = w3b.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER), abi=ROUTER_ABI)
    usdt_c    = w3b.eth.contract(address=Web3.to_checksum_address(BSC_USDT), abi=ERC20_ABI)
    amount_in = int(BNB_RECARGA * 1e18)
    path      = [Web3.to_checksum_address(BSC_USDT), Web3.to_checksum_address(BSC_WBNB)]

    try:
        # Aprovação (se necessário)
        if usdt_c.functions.allowance(wallet, Web3.to_checksum_address(PANCAKE_ROUTER)).call() < amount_in:
            approve = usdt_c.functions.approve(
                Web3.to_checksum_address(PANCAKE_ROUTER), 2**256 - 1
            ).build_transaction({
                "from": wallet, "nonce": w3b.eth.get_transaction_count(wallet),
                "gas": 60000, "gasPrice": w3b.eth.gas_price,
            })
            signed = w3b.eth.account.sign_transaction(approve, pk)
            w3b.eth.wait_for_transaction_receipt(w3b.eth.send_raw_transaction(signed.raw_transaction))

        amounts = router.functions.getAmountsOut(amount_in, path).call()
        swap = router.functions.swapExactTokensForETH(
            amount_in, int(amounts[1] * 0.99), path, wallet, int(time.time()) + 120
        ).build_transaction({
            "from": wallet, "nonce": w3b.eth.get_transaction_count(wallet),
            "gas": 250000, "gasPrice": w3b.eth.gas_price,
        })
        signed  = w3b.eth.account.sign_transaction(swap, pk)
        receipt = w3b.eth.wait_for_transaction_receipt(w3b.eth.send_raw_transaction(signed.raw_transaction))
        return receipt["status"] == 1
    except Exception as e:
        print(Fore.RED + f"  Erro ao recarregar BNB: {e}" + Style.RESET_ALL)
        return False


def setup_bnb_gas(wallet: str, pk: str) -> bool:
    """Verifica BNB e recarrega automaticamente com USDT se estiver baixo."""
    w3b = _w3_bsc()
    bnb = w3b.eth.get_balance(wallet) / 1e18

    if bnb >= BNB_MINIMO:
        print(Fore.GREEN + f"  BNB OK: {bnb:.6f}" + Style.RESET_ALL)
        return True

    print(Fore.YELLOW + f"  BNB baixo ({bnb:.6f}). Trocando ${BNB_RECARGA:.0f} USDT por BNB..." + Style.RESET_ALL)
    ok = _swap_usdt_para_bnb(wallet, pk, w3b)
    if ok:
        bnb = w3b.eth.get_balance(wallet) / 1e18
        print(Fore.GREEN + f"  BNB recarregado: {bnb:.6f}" + Style.RESET_ALL)
    return ok


# ── 4. Monitorar chegada do USDT na BSC ──────────────────────────────────────

def wait_usdt_arrival(wallet: str, min_usdt: float = 1.0):
    print(f"\n  Aguardando USDT chegar na BSC", end="", flush=True)
    w3b  = _w3_bsc()
    usdt = w3b.eth.contract(address=Web3.to_checksum_address(BSC_USDT), abi=ERC20_ABI)
    for _ in range(120):
        bal = usdt.functions.balanceOf(wallet).call() / 1e18
        if bal >= min_usdt:
            print(Fore.GREEN + f"\n  USDT recebido: {bal:.2f}" + Style.RESET_ALL)
            return bal
        print(".", end="", flush=True)
        time.sleep(10)
    print(Fore.YELLOW + "\n  Timeout aguardando USDT." + Style.RESET_ALL)
    return 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not PRIVATE_KEY:
        print(Fore.RED + "PRIVATE_KEY nao configurada no .env")
        return

    w3e    = _w3_eth()
    wallet = w3e.eth.account.from_key(PRIVATE_KEY).address

    print(Fore.CYAN + "\n" + "=" * 65)
    print(Fore.CYAN + "   ARBITRAGEM — Setup")
    print(Fore.CYAN + "=" * 65 + Style.RESET_ALL)
    print(f"\n  Carteira: {wallet}")

    # ── 1. Saldos ─────────────────────────────────────────────────────────────
    print("\n  Verificando saldos...")
    bal       = check_balances(wallet)
    btc_price = _get_btc_price()
    eth_price = 1800.0

    wbtc_usd = bal["wbtc"] * btc_price
    eth_usd  = max(0, bal["eth"] - ETH_GAS_RESERVE) * eth_price
    total_eth_capital = wbtc_usd + eth_usd

    cb_usdt = cb_eth = 0.0
    try:
        from coinbase.rest import RESTClient
        client = RESTClient(
            api_key=os.getenv("COINBASE_API_KEY", ""),
            api_secret=os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n"),
        )
        for acc in client.get_accounts()["accounts"]:
            if acc["currency"] == "USDT":
                cb_usdt = float(acc["available_balance"]["value"])
            if acc["currency"] == "ETH":
                cb_eth  = float(acc["available_balance"]["value"])
    except Exception:
        pass

    print(f"\n  Ethereum:")
    print(f"    ETH  : {bal['eth']:.6f}  (~${bal['eth']*eth_price:.2f})")
    print(f"    WBTC : {bal['wbtc']:.6f}  (~${wbtc_usd:.2f})")
    print(f"  BSC:")
    print(f"    USDT : {bal['bsc_usdt']:.2f}")
    print(f"    BNB  : {bal['bnb']:.6f}")
    print(f"  Coinbase:")
    print(f"    USDT : ${cb_usdt:,.2f}")
    print(f"    ETH  : {cb_eth:.6f}")
    print(f"\n  Total para bridge: ~${total_eth_capital:.2f}")

    # ── 2. Sem nenhum saldo ───────────────────────────────────────────────────
    if bal["bsc_usdt"] < 5 and total_eth_capital < 5:
        print(Fore.RED + "\n  Sem saldo. Deposite ETH ou WBTC na carteira.")
        return

    # ── 3. Oferece bridge se tiver capital na Ethereum ────────────────────────
    if total_eth_capital > 5:
        auto = os.getenv("AUTO_BRIDGE", "").strip().lower()
        if auto == "s":
            resp = "S"
        elif auto == "n":
            resp = "N"
        else:
            print(Fore.CYAN + f"\n  Converter tudo para USDT e enviar para BSC? [S/N]" + Style.RESET_ALL)
            resp = input("  > ").strip().upper()

        if resp == "S":
            # Bridge WBTC → USDT BSC
            if bal["wbtc"] > 0.0001:
                tx = bridge_to_bsc(wallet, bal["wbtc"], PRIVATE_KEY,
                                   from_token=ETH_WBTC, decimals=8, label="WBTC")
                if tx:
                    wait_bridge(tx)

            # Bridge ETH → USDT BSC
            if bal["eth"] > ETH_GAS_RESERVE:
                tx = bridge_to_bsc(wallet, bal["eth"] - ETH_GAS_RESERVE, PRIVATE_KEY,
                                   from_token=NATIVE, decimals=18, label="ETH")
                if tx:
                    wait_bridge(tx)

            wait_usdt_arrival(wallet, min_usdt=bal["bsc_usdt"] + 10)

    # ── 4. Garante BNB para gas ───────────────────────────────────────────────
    if not setup_bnb_gas(wallet, PRIVATE_KEY):
        return

    # ── 5. Ajusta capital com base no saldo real ──────────────────────────────
    bal2      = check_balances(wallet)
    trade_usd = max(5.0, bal2["bsc_usdt"] - 5)
    _update_trade_amount(trade_usd)

    # ── 6. Saldo Coinbase ─────────────────────────────────────────────────────
    _print_coinbase_balances()

    # ── 7. Inicia monitoramento ───────────────────────────────────────────────
    _start_monitoring()


def _print_coinbase_balances():
    cb_usdt = cb_eth = 0.0
    try:
        from coinbase.rest import RESTClient
        client = RESTClient(
            api_key=os.getenv("COINBASE_API_KEY", ""),
            api_secret=os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n"),
        )
        for acc in client.get_accounts()["accounts"]:
            if acc["currency"] == "USDT":
                cb_usdt = float(acc["available_balance"]["value"])
            if acc["currency"] == "ETH":
                cb_eth  = float(acc["available_balance"]["value"])
    except Exception as e:
        print(Fore.RED + f"  Erro ao consultar Coinbase: {e}" + Style.RESET_ALL)
    print(Fore.CYAN + "\n  Saldo Coinbase:" + Style.RESET_ALL)
    print(f"    USDT : ${cb_usdt:,.2f}")
    print(f"    ETH  : {cb_eth:.6f}")


def _update_trade_amount(amount: float):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path, "r") as f:
        lines = f.readlines()
    with open(env_path, "w") as f:
        for line in lines:
            if line.startswith("TRADE_AMOUNT_USD="):
                f.write(f"TRADE_AMOUNT_USD={amount:.2f}\n")
            else:
                f.write(line)
    print(Fore.GREEN + f"  Capital ajustado para ${amount:.2f} USDT" + Style.RESET_ALL)


def _start_monitoring():
    print(Fore.CYAN + "\n  Iniciando monitoramento...\n" + Style.RESET_ALL)
    from main import main as monitor
    monitor()


if __name__ == "__main__":
    main()
