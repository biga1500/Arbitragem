"""
Detecção de oportunidades de arbitragem entre PancakeSwap e Biswap na BSC.
"""

from dataclasses import dataclass

# Taxas de trading por DEX (%)
TRADING_FEES: dict[str, float] = {
    "PancakeSwap": 0.25,
    "Biswap":      0.10,
    "Coinbase":    0.60,
}

GAS_PER_SWAP_USD = 0.10   # ~$0.10 por swap na BSC


@dataclass
class ArbitrageOpportunity:
    buy_exchange: str
    sell_exchange: str
    trade_amount_usd: float

    buy_price: float
    sell_price: float

    gross_profit_usd: float
    gross_profit_pct: float
    buy_fee_unit: float
    sell_fee_unit: float
    gas_usd: float
    net_profit_unit: float
    net_profit_pct: float

    total_spent_usd: float
    total_received_usd: float
    total_fees_usd: float
    total_net_profit_usd: float

    def is_viable(self) -> bool:
        return self.total_net_profit_usd > 0


def find_opportunities(
    prices: dict[str, float | None],
    min_net_profit_percent: float = 0.3,
    trade_amount_usd: float = 50.0,
) -> list[ArbitrageOpportunity]:

    valid     = {k: v for k, v in prices.items() if v is not None}
    exchanges = list(valid.keys())
    results   = []

    for i in range(len(exchanges)):
        for j in range(len(exchanges)):
            if i == j:
                continue

            buy_ex     = exchanges[i]
            sell_ex    = exchanges[j]
            buy_price  = valid[buy_ex]
            sell_price = valid[sell_ex]

            if sell_price <= buy_price:
                continue

            gross_profit_usd = sell_price - buy_price
            gross_profit_pct = (gross_profit_usd / buy_price) * 100

            buy_fee_unit  = buy_price  * (TRADING_FEES.get(buy_ex,  0) / 100)
            sell_fee_unit = sell_price * (TRADING_FEES.get(sell_ex, 0) / 100)
            gas_usd       = GAS_PER_SWAP_USD * 2  # compra + venda

            net_profit_unit = gross_profit_usd - buy_fee_unit - sell_fee_unit - gas_usd
            net_profit_pct  = (net_profit_unit / buy_price) * 100

            if net_profit_pct < min_net_profit_percent:
                continue

            # Calcula para o volume real em USD
            eth_amount         = trade_amount_usd / buy_price
            total_buy_fee      = trade_amount_usd * (TRADING_FEES.get(buy_ex,  0) / 100)
            total_sell_fee     = (eth_amount * sell_price) * (TRADING_FEES.get(sell_ex, 0) / 100)
            total_spent_usd    = trade_amount_usd + total_buy_fee
            total_received_usd = eth_amount * sell_price - total_sell_fee
            total_fees_usd     = total_buy_fee + total_sell_fee + gas_usd
            total_net_profit   = total_received_usd - total_spent_usd - gas_usd

            results.append(ArbitrageOpportunity(
                buy_exchange=buy_ex,
                sell_exchange=sell_ex,
                trade_amount_usd=trade_amount_usd,
                buy_price=buy_price,
                sell_price=sell_price,
                gross_profit_usd=gross_profit_usd,
                gross_profit_pct=gross_profit_pct,
                buy_fee_unit=buy_fee_unit,
                sell_fee_unit=sell_fee_unit,
                gas_usd=gas_usd,
                net_profit_unit=net_profit_unit,
                net_profit_pct=net_profit_pct,
                total_spent_usd=total_spent_usd,
                total_received_usd=total_received_usd,
                total_fees_usd=total_fees_usd,
                total_net_profit_usd=total_net_profit,
            ))

    results.sort(key=lambda o: o.total_net_profit_usd, reverse=True)
    return results
