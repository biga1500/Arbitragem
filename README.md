# Bot de Arbitragem ETH

Bot automatizado que monitora e executa arbitragem de ETH entre **PancakeSwap**, **Biswap** (BSC) e **Coinbase**, calculando lucro líquido após taxas e gas antes de executar qualquer operação.

---

## Como funciona

1. A cada 10 segundos consulta o preço do ETH nas 3 exchanges
2. Calcula se existe oportunidade de lucro líquido acima do limiar configurado
3. Se viável, executa automaticamente: compra na exchange mais barata e vende na mais cara
4. Envia notificação no WhatsApp ao executar (opcional)

**Estratégia:** capital pré-posicionado em USDT — sem necessidade de empréstimos ou flash loans.

---

## Pré-requisitos

- Python 3.11+
- Carteira MetaMask com saldo em USDT na BSC e um pouco de BNB para gas (~$2)
- Conta na Coinbase com saldo em USDT (opcional, mas recomendado)
- Conta Twilio para notificações WhatsApp (opcional)

---

## Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/SEU_USUARIO/SEU_REPO.git
cd SEU_REPO
```

### 2. Instale as dependências

```bash
pip install -r requirements.txt
```

> No Windows, se der erro ao instalar `web3`, instale o Visual C++ Build Tools:
> https://visualstudio.microsoft.com/visual-cpp-build-tools/

### 3. Configure o `.env`

Copie o arquivo de exemplo e preencha com suas chaves:

```bash
cp .env.example .env
```

Edite o `.env` com suas informações:

| Variável | Descrição |
|---|---|
| `PRIVATE_KEY` | Chave privada da MetaMask (sem `0x`) |
| `TRADE_AMOUNT_USD` | Capital por operação em USD |
| `MIN_PROFIT_PERCENT` | Lucro mínimo líquido para executar (recomendado: `0.60`) |
| `COINBASE_API_KEY` | Chave da API Coinbase Advanced Trade |
| `COINBASE_API_SECRET` | Chave privada EC da Coinbase (com `\n` literal nas quebras) |
| `TWILIO_SID` / `TWILIO_TOKEN` | Credenciais Twilio para WhatsApp |

> **NUNCA** compartilhe seu `.env` nem commite no GitHub.

### 4. Configure a Coinbase API

1. Acesse [coinbase.com](https://coinbase.com) → Configurações → API
2. Crie uma nova chave com permissão **trade**
3. Copie o `Key ID` e a chave privada EC para o `.env`
4. A chave privada deve ter `\n` literal (não quebra de linha real) entre as linhas

### 5. Configure o WhatsApp (opcional)

1. Crie conta em [twilio.com](https://twilio.com)
2. Ative o sandbox WhatsApp em: Console → Messaging → Try it out → WhatsApp
3. Envie a mensagem de ativação do sandbox pelo seu WhatsApp
4. Preencha `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` e `TWILIO_TO` no `.env`

---

## Executando

### Iniciar manualmente

```bash
python run.py
```

### Iniciar em background (Windows)

Dê dois cliques no arquivo `iniciar.bat`. O bot vai rodar invisível em background e reiniciar automaticamente se travar.

Para ver o que está acontecendo:

```bash
Get-Content logs\run.log -Wait
```

Para parar:

```bash
taskkill /IM python.exe /F
```

### Iniciar automaticamente com o Windows

Execute o `instalar_tarefa.bat` **uma vez** como administrador. O bot vai iniciar automaticamente 1 minuto após o login.

Para remover a tarefa:

```bash
schtasks /delete /tn "Arbitragem ETH" /f
```

---

## Capital recomendado

| Exchange | Valor sugerido |
|---|---|
| BSC (USDT) | $500–$700 |
| Coinbase (USDT) | $300–$500 |
| BNB para gas | ~$5 (suficiente para semanas) |

> Com menos de $100 as taxas consomem o lucro. Quanto maior o capital, maior o lucro absoluto por operação.

---

## Estrutura dos arquivos

```
├── run.py           # Ponto de entrada — setup + inicia monitoramento
├── main.py          # Loop de monitoramento
├── price_fetcher.py # Consulta preços (DexScreener + Coinbase API)
├── arbitrage.py     # Cálculo de lucro líquido após taxas e gas
├── executor.py      # Execução das ordens (DEX on-chain + Coinbase API)
├── notify.py        # Notificações WhatsApp via Twilio
├── iniciar.bat      # Iniciar em background (Windows)
├── instalar_tarefa.bat  # Instalar como tarefa do Windows
├── .env.example     # Modelo de configuração
└── logs/            # Logs de oportunidades executadas
```

---

## Taxas consideradas no cálculo

| Exchange | Taxa |
|---|---|
| PancakeSwap | 0.25% |
| Biswap | 0.10% |
| Coinbase | 0.60% |
| Gas BSC | ~$0.20 por arbitragem |

---

## Aviso

Este bot executa transações reais com dinheiro real. Use por sua conta e risco. Teste primeiro com valores pequenos e com `MANUAL_CONFIRM=true` para validar o funcionamento antes de deixar automático.
