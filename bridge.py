"""
Bridge automática entre Ethereum e BSC usando Li.Fi API.
Divide o saldo ETH recebido entre as duas redes.
"""
import os
import time
import requests
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

LIFI_API    = "https://li.quest/v1"

# IDs de rede no Li.Fi
CHAIN_ETH   = 1
CHAIN_BSC   = 56

# Tokens nativos
NATIVE      = "0x0000000000000000000000000000000000000000"
BSC_USDT    = "0x55d398326f99059fF775485246999027B3197955"

# Reserva mínima para pagar o gas da própria transação de bridge
ETH_GAS_RESERVE = 0.002   # ~$4 — só para cobrir o gas da bridge


def _eth_web3():
    return Web3(Web3.HTTPProvider(ETH_RPC, request_kwargs={"timeout": 15}))


def _bsc_web3():
    w3 = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(_POAMiddleware, layer=0)
    return w3


def get_balances(wallet: str) -> dict:
    w3_eth = _eth_web3()
    w3_bsc = _bsc_web3()
    return {
        "eth_mainnet": w3_eth.eth.get_balance(wallet) / 1e18,
        "bsc":         w3_bsc.eth.get_balance(wallet) / 1e18,  # BNB
    }


def get_bridge_quote(wallet: str, amount_wei: int) -> dict | None:
    """Consulta o Li.Fi pela melhor rota ETH → USDT na BSC."""
    try:
        resp = requests.get(f"{LIFI_API}/quote", params={
            "fromChain":   CHAIN_ETH,
            "toChain":     CHAIN_BSC,
            "fromToken":   NATIVE,
            "toToken":     BSC_USDT,
            "fromAmount":  str(amount_wei),
            "fromAddress": wallet,
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Li.Fi] Erro ao consultar rota: {e}")
        return None


def wait_bridge(tx_hash: str, from_chain: int, to_chain: int):
    """Monitora o status da bridge até finalizar."""
    print("Monitorando bridge", end="", flush=True)
    for _ in range(60):  # aguarda até 10 minutos
        try:
            resp = requests.get(f"{LIFI_API}/status", params={
                "txHash":    tx_hash,
                "fromChain": from_chain,
                "toChain":   to_chain,
            }, timeout=10)
            data = resp.json()
            status = data.get("status", "UNKNOWN")
            if status == "DONE":
                print(f"\n[OK] Bridge concluida!")
                received = data.get("receiving", {})
                amount   = int(received.get("amount", 0)) / 1e18
                print(f"     Recebido: {amount:.4f} USDT na BSC")
                return True
            elif status == "FAILED":
                print(f"\n[ERRO] Bridge falhou: {data.get('substatusMessage', '')}")
                return False
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(10)
    print("\n[AVISO] Timeout — verifique manualmente no Li.Fi")
    return False


def run_bridge(split_pct: float = 0.5):
    """
    split_pct: fração do saldo ETH a enviar para BSC (padrão 50%).
    O restante fica na Ethereum para Uniswap + gas.
    """
    if not PRIVATE_KEY:
        print("PRIVATE_KEY nao configurada no .env")
        return

    w3_eth = _eth_web3()
    wallet = w3_eth.eth.account.from_key(PRIVATE_KEY).address

    print(f"\nCarteira: {wallet}")
    print("-" * 60)

    # Saldos atuais
    balances = get_balances(wallet)
    eth_bal  = balances["eth_mainnet"]
    bnb_bal  = balances["bsc"]

    print(f"ETH (Ethereum) : {eth_bal:.6f} ETH")
    print(f"BNB (BSC)      : {bnb_bal:.6f} BNB")

    if eth_bal <= ETH_GAS_RESERVE:
        print(f"\nSaldo ETH insuficiente. Precisa de mais de {ETH_GAS_RESERVE} ETH.")
        return

    # Calcula quanto enviar
    disponivel   = eth_bal - ETH_GAS_RESERVE
    bridge_amount = disponivel * split_pct
    amount_wei    = int(bridge_amount * 1e18)

    print(f"\nPlano de divisao:")
    print(f"  Reserva gas ETH  : {ETH_GAS_RESERVE:.4f} ETH  (~${ ETH_GAS_RESERVE*1800:.0f})")
    print(f"  Fica na Ethereum : {disponivel * (1 - split_pct):.6f} ETH  ({(1-split_pct)*100:.0f}%)")
    print(f"  Bridge para BSC  : {bridge_amount:.6f} ETH  ({split_pct*100:.0f}%)")
    print("-" * 60)

    # Cotacao da bridge
    print("Buscando melhor rota de bridge...")
    quote = get_bridge_quote(wallet, amount_wei)
    if not quote:
        return

    # Detalhes da rota
    tool         = quote.get("toolDetails", {}).get("name", "?")
    est_out      = int(quote.get("estimate", {}).get("toAmount", 0)) / 1e18
    fee_costs    = quote.get("estimate", {}).get("feeCosts", [])
    total_fee    = sum(float(f.get("amountUSD", 0)) for f in fee_costs)
    est_time     = quote.get("estimate", {}).get("executionDuration", 0)

    print(f"\nRota encontrada  : {tool}")
    print(f"Voce envia       : {bridge_amount:.6f} ETH")
    print(f"Voce recebe      : ~{est_out:.2f} USDT na BSC")
    print(f"Taxa da bridge   : ~${total_fee:.2f}")
    print(f"Tempo estimado   : ~{est_time//60:.0f} min")
    print("-" * 60)
    print("[S] Confirmar bridge   [N] Cancelar")

    resp = input("> ").strip().upper()
    if resp != "S":
        print("Cancelado.")
        return

    # Executa a transacao
    tx_data     = quote["transactionRequest"]
    nonce       = w3_eth.eth.get_transaction_count(wallet)

    tx = {
        "from":     wallet,
        "to":       tx_data["to"],
        "data":     tx_data["data"],
        "value":    int(tx_data["value"], 16) if isinstance(tx_data["value"], str) else tx_data["value"],
        "gas":      int(tx_data.get("gasLimit", 300000), 16) if isinstance(tx_data.get("gasLimit"), str) else tx_data.get("gasLimit", 300000),
        "gasPrice": int(tx_data.get("gasPrice", w3_eth.eth.gas_price), 16) if isinstance(tx_data.get("gasPrice"), str) else tx_data.get("gasPrice", w3_eth.eth.gas_price),
        "nonce":    nonce,
        "chainId":  CHAIN_ETH,
    }

    signed  = w3_eth.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3_eth.eth.send_raw_transaction(signed.raw_transaction)
    tx_hex  = tx_hash.hex()

    print(f"\n[OK] Transacao enviada: {tx_hex}")
    print(f"     Ver em: https://etherscan.io/tx/{tx_hex}")

    wait_bridge(tx_hex, CHAIN_ETH, CHAIN_BSC)

    # Saldos finais
    print("\nSaldos finais:")
    balances = get_balances(wallet)
    print(f"  ETH (Ethereum) : {balances['eth_mainnet']:.6f} ETH")
    print(f"  BNB (BSC)      : {balances['bsc']:.6f} BNB")
    print("\nPasso seguinte: python setup_wallet.py")


if __name__ == "__main__":
    run_bridge(split_pct=1.0)  # 100% vai para BSC
