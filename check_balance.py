"""
Verifica saldos da carteira nas redes BSC e Ethereum.
"""
import os
from dotenv import load_dotenv
from web3 import Web3

try:
    from web3.middleware import ExtraDataToPOAMiddleware as _POAMiddleware
except ImportError:
    from web3.middleware import geth_poa_middleware as _POAMiddleware

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
BSC_RPC     = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
ETH_RPC     = os.getenv("ETH_RPC_URL", "https://ethereum.publicnode.com")

BSC_USDT  = "0x55d398326f99059fF775485246999027B3197955"
ETH_USDC  = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
ETH_USDT  = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

ERC20_ABI = [{"name":"balanceOf","type":"function","inputs":[{"name":"account","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"}]

TRADE_USD = float(os.getenv("TRADE_AMOUNT_USD", "100.0"))
GAS_BSC   = 0.50   # BNB em USD estimado para gas
GAS_ETH   = 5.00   # ETH em USD estimado para gas

def check(label, ok, detail=""):
    icon = "[OK]" if ok else "[--]"
    print(f"  {icon}  {label:<45} {detail}")

def token_balance(w3, token_addr, wallet, decimals):
    contract = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    raw = contract.functions.balanceOf(wallet).call()
    return raw / 10**decimals

if not PRIVATE_KEY:
    print("PRIVATE_KEY não configurada no .env")
    exit(1)

account = Web3().eth.account.from_key(PRIVATE_KEY)
wallet  = account.address
print(f"\nCarteira: {wallet}\n")

# ── BSC ───────────────────────────────────────────────────────────────────────
print("-- BSC (PancakeSwap) " + "-"*44)
try:
    w3_bsc = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout":10}))
    w3_bsc.middleware_onion.inject(_POAMiddleware, layer=0)

    bnb   = w3_bsc.eth.get_balance(wallet) / 1e18
    usdt  = token_balance(w3_bsc, BSC_USDT, wallet, 18)

    check("Conectado à BSC",          w3_bsc.is_connected())
    check(f"BNB (gas)  — precisa ~$0.50",  bnb * 300 >= GAS_BSC,  f"{bnb:.6f} BNB")
    check(f"USDT       — precisa ${TRADE_USD:.0f}",   usdt >= TRADE_USD, f"{usdt:.2f} USDT")
except Exception as e:
    print(f"  ✗  Erro BSC: {e}")

print()

# ── Ethereum ──────────────────────────────────────────────────────────────────
print("-- Ethereum (Uniswap) " + "-"*43)
try:
    w3_eth = Web3(Web3.HTTPProvider(ETH_RPC, request_kwargs={"timeout":10}))

    eth   = w3_eth.eth.get_balance(wallet) / 1e18
    usdc  = token_balance(w3_eth, ETH_USDC, wallet, 6)
    usdt_eth = token_balance(w3_eth, ETH_USDT, wallet, 6)

    check("Conectado à Ethereum",       w3_eth.is_connected())
    check(f"ETH (gas)  — precisa ~$5",  eth * 1800 >= GAS_ETH,  f"{eth:.6f} ETH")
    check(f"USDC       — precisa ${TRADE_USD:.0f}",  usdc >= TRADE_USD, f"{usdc:.2f} USDC")
    check(f"USDT (ETH) — alternativa",  usdt_eth > 0,            f"{usdt_eth:.2f} USDT")
except Exception as e:
    print(f"  ✗  Erro Ethereum: {e}")

print()
