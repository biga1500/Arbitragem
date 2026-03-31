"""
Gera gráfico de discrepância de preços ETH entre exchanges ao longo do tempo.
Lê logs/precos.csv gerado pelo monitoramento.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

CSV = Path(__file__).parent / "logs" / "precos.csv"

if not CSV.exists():
    print("Arquivo logs/precos.csv não encontrado. Deixe o monitoramento rodar por um tempo.")
    exit(1)

df = pd.read_csv(CSV, parse_dates=["timestamp"])

if len(df) < 2:
    print(f"Apenas {len(df)} registro(s). Aguarde mais dados.")
    exit(1)

df = df.sort_values("timestamp")
df["hora"] = df["timestamp"].dt.hour

exchanges = [c for c in df.columns if c not in ("timestamp", "hora", "spread_usd", "spread_pct")]
for col in exchanges:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df["spread_pct"] = pd.to_numeric(df["spread_pct"], errors="coerce")

fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=False)
fig.suptitle("Análise de Discrepância ETH/USDT", fontsize=14, fontweight="bold")

# ── 1. Preços ao longo do tempo ──────────────────────────────────────────────
ax1 = axes[0]
colors = ["#f0a500", "#00bcd4", "#4caf50", "#e91e63"]
for i, ex in enumerate(exchanges):
    if df[ex].notna().any():
        ax1.plot(df["timestamp"], df[ex], label=ex, linewidth=1.2,
                 color=colors[i % len(colors)])
ax1.set_ylabel("Preço ETH (USD)")
ax1.set_title("Preços por exchange")
ax1.legend(loc="upper left", fontsize=8)
ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)
ax1.grid(True, alpha=0.3)

# ── 2. Spread % ao longo do tempo ────────────────────────────────────────────
ax2 = axes[1]
ax2.fill_between(df["timestamp"], df["spread_pct"], alpha=0.4, color="#f0a500")
ax2.plot(df["timestamp"], df["spread_pct"], color="#f0a500", linewidth=1)
ax2.axhline(y=0.60, color="red", linestyle="--", linewidth=1, label="Limiar 0.60%")
ax2.set_ylabel("Spread (%)")
ax2.set_title("Discrepância % entre exchanges")
ax2.legend(fontsize=8)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)
ax2.grid(True, alpha=0.3)

# ── 3. Média de spread por hora do dia ───────────────────────────────────────
ax3 = axes[2]
hora_media = df.groupby("hora")["spread_pct"].mean()
bars = ax3.bar(hora_media.index, hora_media.values, color="#00bcd4", alpha=0.8, width=0.7)
ax3.axhline(y=0.60, color="red", linestyle="--", linewidth=1, label="Limiar 0.60%")

# destaca a hora com maior média
if not hora_media.empty:
    melhor_hora = hora_media.idxmax()
    ax3.bar(melhor_hora, hora_media[melhor_hora], color="#4caf50", alpha=0.9, width=0.7)
    ax3.annotate(f"Pico: {melhor_hora}h ({hora_media[melhor_hora]:.3f}%)",
                 xy=(melhor_hora, hora_media[melhor_hora]),
                 xytext=(melhor_hora + 0.5, hora_media[melhor_hora] + 0.02),
                 fontsize=8, color="#4caf50")

ax3.set_xlabel("Hora do dia")
ax3.set_ylabel("Spread médio (%)")
ax3.set_title("Média de discrepância por hora do dia")
ax3.set_xticks(range(0, 24))
ax3.legend(fontsize=8)
ax3.grid(True, alpha=0.3, axis="y")

plt.tight_layout()
out = Path(__file__).parent / "logs" / "discrepancia.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Gráfico salvo em: {out}")
plt.show()
