"""
Setup inicial da carteira: troca uma pequena parte do USDT por BNB para gas.
Rode UMA vez após depositar USDT na BSC.
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

PANCAKE_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
BSC_USDT       = "0x55d398326f99059fF775485246999027B3197955"
BSC_WBNB       = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

ROUTER_ABI = [
    {"name":"swapExactTokensForETH","type":"function","inputs":[
        {"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},
        {"name":"path","type":"address[]"},{"name":"to","type":"address"},
        {"name":"deadline","type":"uint256"}],"outputs":[{"name":"amounts","type":"uint256[]"}]},
    {"name":"getAmountsOut","type":"function","inputs":[
        {"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],
        "outputs":[{"name":"amounts","type":"uint256[]"}]},
]
ERC20_ABI = [
    {"name":"approve","type":"function","inputs":[
        {"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
        "outputs":[{"name":"","type":"bool"}]},
    {"name":"balanceOf","type":"function","inputs":[
        {"name":"account","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},
]

BNB_RESERVA_USD = 2.0   # quanto trocar de USDT para BNB

def main():
    if not PRIVATE_KEY:
        print("PRIVATE_KEY nao configurada no .env")
        return

    w3     = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(_POAMiddleware, layer=0)
    wallet = w3.eth.account.from_key(PRIVATE_KEY).address

    # Verifica saldo USDT
    usdt_contract = w3.eth.contract(address=Web3.to_checksum_address(BSC_USDT), abi=ERC20_ABI)
    usdt_balance  = usdt_contract.functions.balanceOf(wallet).call() / 1e18

    print(f"Carteira : {wallet}")
    print(f"USDT     : {usdt_balance:.2f}")
    print(f"BNB atual: {w3.eth.get_balance(wallet)/1e18:.6f}")

    if usdt_balance < BNB_RESERVA_USD + 10:
        print(f"\nSaldo insuficiente. Deposite pelo menos ${BNB_RESERVA_USD + 10:.0f} USDT e tente novamente.")
        return

    print(f"\nVou trocar ${BNB_RESERVA_USD:.2f} de USDT por BNB para gas.")
    resp = input("Confirmar? [S/N] > ").strip().upper()
    if resp != "S":
        print("Cancelado.")
        return

    router     = w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER), abi=ROUTER_ABI)
    amount_in  = int(BNB_RESERVA_USD * 1e18)
    path       = [Web3.to_checksum_address(BSC_USDT), Web3.to_checksum_address(BSC_WBNB)]

    # Aprovação
    print("Aprovando USDT...")
    approve_tx = usdt_contract.functions.approve(
        Web3.to_checksum_address(PANCAKE_ROUTER), 2**256 - 1
    ).build_transaction({
        "from": wallet, "nonce": w3.eth.get_transaction_count(wallet),
        "gas": 60000, "gasPrice": w3.eth.gas_price,
    })
    signed = w3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))

    # Swap USDT → BNB
    print("Trocando USDT por BNB...")
    amounts    = router.functions.getAmountsOut(amount_in, path).call()
    amount_min = int(amounts[1] * 0.99)

    import time
    swap_tx = router.functions.swapExactTokensForETH(
        amount_in, amount_min, path, wallet, int(time.time()) + 120
    ).build_transaction({
        "from": wallet, "nonce": w3.eth.get_transaction_count(wallet),
        "gas": 250000, "gasPrice": w3.eth.gas_price,
    })
    signed  = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
    receipt = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_raw_transaction(signed.raw_transaction)
    )

    if receipt["status"] == 1:
        bnb_novo = w3.eth.get_balance(wallet) / 1e18
        print(f"\n[OK] BNB agora: {bnb_novo:.6f}")
        print(f"[OK] Carteira pronta para operar!")
    else:
        print("\n[ERRO] Transacao revertida.")

if __name__ == "__main__":
    main()
