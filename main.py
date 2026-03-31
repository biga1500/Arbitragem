"""
Arbitragem ETH entre PancakeSwap e Biswap na BSC.
Estratégia: capital pré-posicionado em USDT, execução sequencial na mesma rede.
"""

import os
import time
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from colorama import init, Fore, Style

from price_fetcher import fetch_all_prices
from arbitrage import find_opportunities
from executor import execute_arbitrage
from notify import notify_execution

load_dotenv()
init(autoreset=True)

MIN_PROFIT_PERCENT = float(os.getenv("MIN_PROFIT_PERCENT", "0.3"))
TRADE_AMOUNT_USD   = float(os.getenv("TRADE_AMOUNT_USD", "50.0"))
INTERVAL_SECONDS   = int(os.getenv("INTERVAL_SECONDS", "10"))
PRIVATE_KEY        = os.getenv("PRIVATE_KEY", "")
MANUAL_CONFIRM     = os.getenv("MANUAL_CONFIRM", "false").lower() == "true"

SEP = "-" * 65

# --- Logger ---
LOGS_DIR  = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
_log_file = LOGS_DIR / f"oportunidades_{datetime.now().strftime('%Y-%m-%d')}.log"
_logger   = logging.getLogger("arbitragem")
_logger.setLevel(logging.INFO)
_fh = logging.FileHandler(_log_file, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_fh)

def log_opportunity(opp):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _logger.info(
        f"[{ts}] {opp.buy_exchange} -> {opp.sell_exchange} | "
        f"${opp.trade_amount_usd:.2f} USD | "
        f"Compra: ${opp.buy_price:,.2f} | Venda: ${opp.sell_price:,.2f} | "
        f"Gasto: ${opp.total_spent_usd:.4f} | Recebido: ${opp.total_received_usd:.4f} | "
        f"Taxas: ${opp.total_fees_usd:.4f} | "
        f"Lucro liquido: ${opp.total_net_profit_usd:.4f} ({opp.net_profit_pct:.3f}%)"
    )


def print_header():
    print(Fore.CYAN + "=" * 65)
    print(Fore.CYAN + "   ARBITRAGEM ETH — PancakeSwap / Biswap / Coinbase")
    print(Fore.CYAN + "=" * 65)
    print(f"  Capital por operacao : ${TRADE_AMOUNT_USD:.2f} USDT")
    print(f"  Limiar lucro liquido : {MIN_PROFIT_PERCENT}%  |  Intervalo: {INTERVAL_SECONDS}s")
    print(f"  Taxas : PancakeSwap 0.25% | Biswap 0.10% | Coinbase 0.60%")
    if PRIVATE_KEY:
        from web3 import Web3
        wallet = Web3().eth.account.from_key(PRIVATE_KEY).address
        print(f"  Wallet: {wallet}")
    else:
        print(f"  Wallet: {Fore.RED}NAO CONFIGURADA — apenas monitoramento{Style.RESET_ALL}")
    print(f"  Log   : {_log_file}")
    print(Fore.CYAN + "=" * 65 + Style.RESET_ALL)


def print_prices(prices: dict):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n{Fore.WHITE}[{ts}] Precos ETH/USDT na BSC:")
    for exchange, price in prices.items():
        if price is None:
            print(f"    {Fore.RED}{exchange:<14} INDISPONIVEL")
        else:
            print(f"    {Fore.YELLOW}{exchange:<14} ${price:,.2f}")


def print_opportunity(opp):
    color  = Fore.GREEN if opp.is_viable() else Fore.YELLOW
    status = "[VIAVEL]" if opp.is_viable() else "[MARGINAL]"
    usd    = opp.trade_amount_usd

    print(color + f"\n  {status}  {opp.buy_exchange}  ->  {opp.sell_exchange}  (${usd:.2f} USDT)" + Style.RESET_ALL)
    print(f"  {SEP}")
    print(f"  {'':28}  {'Compra':>12}  {'Venda':>12}")
    print(f"  {'Cotacao ETH':28}  ${opp.buy_price:>11,.2f}  ${opp.sell_price:>11,.2f}")
    print(f"  {'Taxa de trading':28}  ${opp.buy_fee_unit:>11.4f}  ${opp.sell_fee_unit:>11.4f}")
    print(f"  {'Gas (2 txs)':28}                ${opp.gas_usd:>11.4f}")
    print(f"  {SEP}")
    print(f"  {'Voce vai GASTAR':<40}  ${opp.total_spent_usd:>10,.4f}")
    print(f"  {'Voce vai RECEBER':<40}  ${opp.total_received_usd:>10,.4f}")
    print(f"  {'Total taxas + gas':<40}  ${opp.total_fees_usd:>10,.4f}")
    print(color + f"  {'LUCRO LIQUIDO':<40}  ${opp.total_net_profit_usd:>10,.4f}  ({opp.net_profit_pct:.3f}%)" + Style.RESET_ALL)
    print(f"  {SEP}")


def _print_balances(wallet_addr: str):
    try:
        from web3 import Web3
        try:
            from web3.middleware import ExtraDataToPOAMiddleware as _POA
        except ImportError:
            from web3.middleware import geth_poa_middleware as _POA

        bsc_rpc = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
        w3b     = Web3(Web3.HTTPProvider(bsc_rpc, request_kwargs={"timeout": 10}))
        w3b.middleware_onion.inject(_POA, layer=0)

        usdt_abi = [{"name":"balanceOf","type":"function","inputs":[{"name":"account","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"}]
        usdt_c   = w3b.eth.contract(address=Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955"), abi=usdt_abi)
        bsc_usdt = usdt_c.functions.balanceOf(wallet_addr).call() / 1e18
        bnb      = w3b.eth.get_balance(wallet_addr) / 1e18
    except Exception:
        bsc_usdt = bnb = 0

    cb_usdt = cb_eth = 0
    try:
        from coinbase.rest import RESTClient
        client = RESTClient(
            api_key=os.getenv("COINBASE_API_KEY",""),
            api_secret=os.getenv("COINBASE_API_SECRET","").replace("\\n","\n"),
        )
        for acc in client.get_accounts()["accounts"]:
            if acc["currency"] == "USDT":
                cb_usdt = float(acc["available_balance"]["value"])
            if acc["currency"] == "ETH":
                cb_eth  = float(acc["available_balance"]["value"])
    except Exception:
        pass

    total = bsc_usdt + cb_usdt
    print(Fore.CYAN + "\n  Saldos disponíveis:" + Style.RESET_ALL)
    print(f"    BSC      — USDT: ${bsc_usdt:,.2f}  |  BNB: {bnb:.5f}")
    print(f"    Coinbase — USDT: ${cb_usdt:,.2f}  |  ETH: {cb_eth:.5f}")
    print(Fore.CYAN + f"    TOTAL capital de trading: ${total:,.2f}" + Style.RESET_ALL)
    print()


def main():
    print_header()

    from web3 import Web3
    wallet_addr = Web3().eth.account.from_key(PRIVATE_KEY).address if PRIVATE_KEY else ""

    _print_balances(wallet_addr)
    print(f"Monitorando... (Ctrl+C para parar)\n")

    iteration = 0
    while True:
        iteration += 1
        try:
            prices = fetch_all_prices()
            print_prices(prices)

            opportunities = find_opportunities(
                prices,
                min_net_profit_percent=MIN_PROFIT_PERCENT,
                trade_amount_usd=TRADE_AMOUNT_USD,
            )

            if opportunities:
                for opp in opportunities:
                    print_opportunity(opp)
                    log_opportunity(opp)

                    if not PRIVATE_KEY:
                        continue

                    if MANUAL_CONFIRM:
                        print(Fore.CYAN + f"\n  Executar? {opp.buy_exchange} -> {opp.sell_exchange}")
                        print(Fore.CYAN + f"  Capital: ${TRADE_AMOUNT_USD:.2f} | Lucro estimado: ${opp.total_net_profit_usd:.4f}")
                        print(Fore.CYAN +  "  [S] Confirmar   [N] Pular   [Q] Sair" + Style.RESET_ALL)
                        try:
                            resp = input("  > ").strip().upper()
                        except (EOFError, KeyboardInterrupt):
                            resp = "Q"
                        if resp == "Q":
                            print(Fore.CYAN + "\nMonitoramento encerrado.")
                            return
                        elif resp != "S":
                            print("  Pulado.\n")
                            continue

                    # Garante BNB suficiente antes de executar
                    from run import setup_bnb_gas
                    setup_bnb_gas(wallet_addr, PRIVATE_KEY)

                    print(Fore.YELLOW + "  Executando...")
                    buy_r, sell_r = execute_arbitrage(
                        opp.buy_exchange, opp.sell_exchange, TRADE_AMOUNT_USD, PRIVATE_KEY
                    )
                    print((Fore.GREEN if buy_r.success  else Fore.RED) + f"  {buy_r}")
                    print((Fore.GREEN if sell_r.success else Fore.RED) + f"  {sell_r}" + Style.RESET_ALL)
                    _logger.info(f"  EXECUCAO | {buy_r} | {sell_r}")
                    notify_execution(buy_r, sell_r, opp)
            else:
                print(Fore.WHITE + "  Nenhuma oportunidade acima do limiar.")

            print()
        except KeyboardInterrupt:
            print(Fore.CYAN + "\nMonitoramento encerrado.")
            break
        except Exception as e:
            print(Fore.RED + f"  Erro na iteracao {iteration}: {e}")

        try:
            time.sleep(INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print(Fore.CYAN + "\nMonitoramento encerrado.")
            break


if __name__ == "__main__":
    main()
