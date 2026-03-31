"""
Notificações WhatsApp via Twilio.
"""
import os
from dotenv import load_dotenv

load_dotenv()

_sid   = os.getenv("TWILIO_SID", "")
_token = os.getenv("TWILIO_TOKEN", "")
_from  = os.getenv("TWILIO_FROM", "")
_to    = os.getenv("TWILIO_TO", "")


def send_whatsapp(msg: str) -> bool:
    try:
        from twilio.rest import Client
        Client(_sid, _token).messages.create(body=msg, from_=_from, to=_to)
        return True
    except Exception as e:
        print(f"  [WhatsApp] Erro: {e}")
        return False


def notify_execution(buy_r, sell_r, opp):
    if not _sid:
        return
    status = "SUCESSO" if buy_r.success and sell_r.success else "FALHOU"
    msg = (
        f"*Arbitragem {status}*\n"
        f"{opp.buy_exchange} -> {opp.sell_exchange}\n"
        f"Capital: ${opp.trade_amount_usd:.2f}\n"
        f"Lucro liquido: ${opp.total_net_profit_usd:.4f} ({opp.net_profit_pct:.3f}%)\n"
        f"Compra TX: {buy_r.tx_hash}\n"
        f"Venda TX:  {sell_r.tx_hash}"
    )
    send_whatsapp(msg)


if __name__ == "__main__":
    ok = send_whatsapp("Teste do sistema de arbitragem - tudo funcionando!")
    print("Mensagem enviada!" if ok else "Falhou.")
