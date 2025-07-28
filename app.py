# --- app.py (Versão FINAL para Nuvem/Produção) ---
# ATENÇÃO: ESTE CÓDIGO USA DINHEIRO REAL. USE POR SUA CONTA E RISCO.
import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np
import threading
import time
import datetime

# --- CONFIGURAÇÃO INICIAL ---
app = Flask(__name__)
# A SECRET_KEY é importante para produção, pode ser qualquer coisa complexa.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma-chave-secreta-padrao-pode-mudar')
socketio = SocketIO(app)

# --- VARIÁVEIS GLOBAIS ---
client = None
bot_thread = None
is_bot_running = False
trade_history = [] 

# --- FUNÇÕES DO BOT (Nenhuma alteração aqui, são as mesmas de antes) ---

def log_to_frontend(message, event_type='info'):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"LOG: [{timestamp}][{event_type.upper()}] {message}")
    socketio.emit('log_update', {'type': event_type, 'message': message, 'timestamp': timestamp})

def update_portfolio_on_frontend():
    if not client: return
    try:
        usdt_balance = client.get_asset_balance(asset='USDT')['free']
        btc_balance = client.get_asset_balance(asset='BTC')['free']
        socketio.emit('portfolio_update', {
            'usdt': f"{float(usdt_balance):.2f}",
            'btc': f"{float(btc_balance):.8f}"
        })
    except Exception as e:
        log_to_frontend(f"Erro ao buscar portfólio: {e}", 'error')

def add_trade_to_history(trade_type, price, qty):
    global trade_history
    trade = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'type': trade_type,
        'price': f"{price:.2f}",
        'qty': f"{qty:.8f}"
    }
    trade_history.append(trade)
    socketio.emit('history_update', trade_history)

def trading_bot_logic():
    global is_bot_running
    log_to_frontend("Iniciando estratégia: Crossover de Médias Móveis com Stop-Loss...", 'success')

    SHORT_WINDOW, LONG_WINDOW = 20, 50
    TRADE_SYMBOL, KLINE_INTERVAL = 'BTCUSDT', Client.KLINE_INTERVAL_1MINUTE
    TRADE_QUANTITY_USDT = 15.0
    STOP_LOSS_PERCENTAGE = 0.02

    in_position = False
    last_purchase_price = 0

    try:
        current_price = float(client.get_ticker(symbol=TRADE_SYMBOL)['lastPrice'])
        btc_balance = float(client.get_asset_balance(asset='BTC')['free'])
        if btc_balance * current_price > 10.0:
            in_position = True
            last_purchase_price = current_price
            log_to_frontend(f"Detectado saldo inicial de {btc_balance:.8f} BTC. Assumindo posição comprada.", 'warn')
            log_to_frontend(f"Stop-Loss inicial definido em ${last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):,.2f}", 'warn')
    except Exception as e:
        log_to_frontend(f"Não foi possível verificar saldo inicial: {e}", 'error')

    while is_bot_running:
        try:
            klines = client.get_klines(symbol=TRADE_SYMBOL, interval=KLINE_INTERVAL, limit=LONG_WINDOW + 5)
            candlestick_data = [{'time': k[0] / 1000, 'open': float(k[1]), 'high': float(k[2]), 'low': float(k[3]), 'close': float(k[4])} for k in klines]
            socketio.emit('kline_update', candlestick_data)
            
            close_prices = np.array([k['close'] for k in candlestick_data], dtype=float)
            current_price = close_prices[-1]

            # Lógica de Stop-Loss (sem alterações)
            if in_position and current_price < last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):
                log_to_frontend(f"STOP-LOSS ATINGIDO! Preço caiu abaixo de ${last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):,.2f}. Vendendo...", 'error')
                try:
                    btc_balance_to_sell = float(client.get_asset_balance(asset='BTC')['free'])
                    if btc_balance_to_sell > 0.00001:
                        order = client.order_market_sell(symbol=TRADE_SYMBOL, quantity=f"{btc_balance_to_sell:.5f}")
                        in_position = False
                        # ... resto da lógica ...
                except Exception as e:
                    # ...
                time.sleep(60)
                continue

            # Lógica de Médias Móveis (sem alterações)
            if len(close_prices) < LONG_WINDOW:
                # ...
                time.sleep(60)
                continue
            
            # ... resto da lógica de compra e venda ...
            
            time.sleep(60)
        except Exception as e:
            log_to_frontend(f"Erro CRÍTICO no loop da estratégia: {e}", 'error')
            time.sleep(60)

# --- ROTAS E EVENTOS DO SERVIDOR (COM MUDANÇAS) ---
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    # Agora o bot inicia automaticamente se as chaves estiverem configuradas
    log_to_frontend("Cliente conectado ao servidor. A tentar iniciar o bot...", 'info')
    handle_start_bot()

@socketio.on('start_bot')
def handle_start_bot():
    global client, bot_thread, is_bot_running, trade_history
    if is_bot_running:
        log_to_frontend("Bot já está em execução.", 'warn')
        return

    # AQUI ESTÁ A GRANDE MUDANÇA: LER AS CHAVES DO AMBIENTE DO SERVIDOR
    api_key = os.environ.get('BINANCE_API_KEY')
    api_secret = os.environ.get('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        log_to_frontend("ERRO: As chaves BINANCE_API_KEY e BINANCE_API_SECRET não foram configuradas no servidor.", 'error')
        return

    log_to_frontend("A tentar conectar à conta REAL da Binance...", 'warn')
    trade_history = []
    try:
        client = Client(api_key, api_secret)
        client.get_account()
        log_to_frontend("Conexão com a conta REAL da Binance bem-sucedida!", 'success')
        update_portfolio_on_frontend()
        is_bot_running = True
        bot_thread = threading.Thread(target=trading_bot_logic)
        bot_thread.start()
        emit('bot_status', {'running': True})
    except Exception as e:
        log_to_frontend(f"Falha na conexão: {e}", 'error')
        emit('bot_status', {'running': False})

@socketio.on('stop_bot')
def handle_stop_bot():
    # ... sem alterações aqui ...
    global is_bot_running, bot_thread, client
    # ...

@socketio.on('disconnect')
def handle_disconnect():
    print("Cliente desconectado!")

# O Chatbot continua igual, mas sem a necessidade de verificar a conexão aqui
@socketio.on('send_chat_message')
def handle_chat_message(data):
    # ... sem alterações aqui ...
    user_message = data['message'].lower().strip()
    # ...
    
# O if __name__ == '__main__': é removido porque o Gunicorn irá iniciar a app.
