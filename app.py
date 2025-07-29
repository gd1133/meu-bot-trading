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

# --- FUNÇÕES DO BOT ---

def log_to_frontend(message, event_type='info'):
    """Envia uma mensagem de log para o frontend via WebSocket."""
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"LOG: [{timestamp}][{event_type.upper()}] {message}")
    socketio.emit('log_update', {'type': event_type, 'message': message, 'timestamp': timestamp})

def update_portfolio_on_frontend():
    """Busca o saldo da conta na Binance e envia para o frontend."""
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
    """Adiciona uma nova operação ao histórico e envia para o frontend."""
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
    """Lógica de trading com Crossover de Médias Móveis e Stop-Loss."""
    global is_bot_running
    log_to_frontend("Iniciando estratégia: Crossover de Médias Móveis com Stop-Loss...", 'success')

    # Constantes da Estratégia
    SHORT_WINDOW, LONG_WINDOW = 20, 50
    TRADE_SYMBOL, KLINE_INTERVAL = 'BTCUSDT', Client.KLINE_INTERVAL_1MINUTE
    TRADE_QUANTITY_USDT = 15.0
    STOP_LOSS_PERCENTAGE = 0.02  # 2% de stop-loss

    # Estado da Estratégia
    in_position = False
    last_purchase_price = 0

    try:
        current_price = float(client.get_ticker(symbol=TRADE_SYMBOL)['lastPrice'])
        btc_balance = float(client.get_asset_balance(asset='BTC')['free'])
        if btc_balance * current_price > 10.0: # Verifica se tem mais de 10 USDT em BTC
            in_position = True
            last_purchase_price = current_price
            log_to_frontend(f"Detectado saldo inicial de {btc_balance:.8f} BTC. Assumindo posição comprada.", 'warn')
            log_to_frontend(f"Stop-Loss inicial definido em ${last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):,.2f}", 'warn')
    except Exception as e:
        log_to_frontend(f"Não foi possível verificar saldo inicial: {e}", 'error')

    # Loop Principal
    while is_bot_running:
        try:
            klines = client.get_klines(symbol=TRADE_SYMBOL, interval=KLINE_INTERVAL, limit=LONG_WINDOW + 5)
            candlestick_data = [{'time': k[0] / 1000, 'open': float(k[1]), 'high': float(k[2]), 'low': float(k[3]), 'close': float(k[4])} for k in klines]
            socketio.emit('kline_update', candlestick_data)
            
            close_prices = np.array([k['close'] for k in candlestick_data], dtype=float)
            current_price = close_prices[-1]

            # Lógica de Stop-Loss
            if in_position and current_price < last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):
                log_to_frontend(f"STOP-LOSS ATINGIDO! Preço caiu abaixo de ${last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):,.2f}. Vendendo...", 'error')
                try:
                    btc_balance_to_sell = float(client.get_asset_balance(asset='BTC')['free'])
                    if btc_balance_to_sell > 0.00001:
                        order = client.order_market_sell(symbol=TRADE_SYMBOL, quantity=f"{btc_balance_to_sell:.5f}")
                        executed_qty = float(order['executedQty'])
                        log_to_frontend(f"ORDEM DE VENDA (STOP-LOSS) EXECUTADA: {executed_qty:.8f} BTC", 'success')
                        in_position = False
                        last_purchase_price = 0
                        add_trade_to_history('venda (stop)', current_price, executed_qty)
                        update_portfolio_on_frontend()
                except Exception as e:
                    log_to_frontend(f"ERRO AO EXECUTAR STOP-LOSS: {e}", 'error')
                time.sleep(60)
                continue

            # Lógica de Médias Móveis
            if len(close_prices) < LONG_WINDOW:
                log_to_frontend(f"Aguardando dados suficientes... ({len(close_prices)}/{LONG_WINDOW})", 'info')
                time.sleep(60)
                continue

            short_sma = np.mean(close_prices[-SHORT_WINDOW:])
            long_sma = np.mean(close_prices[-LONG_WINDOW:])
            prev_short_sma = np.mean(close_prices[-SHORT_WINDOW-1:-1])
            prev_long_sma = np.mean(close_prices[-LONG_WINDOW-1:-1])
            
            log_to_frontend(f"Preço: ${current_price:,.2f} | SMA Curta: {short_sma:,.2f} | SMA Longa: {long_sma:,.2f}", 'info')

            # Sinal de Compra (Golden Cross)
            if prev_short_sma <= prev_long_sma and short_sma > long_sma and not in_position:
                log_to_frontend(f"SINAL DE COMPRA (Golden Cross)! Tentando comprar.", 'warn')
                try:
                    qty = TRADE_QUANTITY_USDT / current_price
                    order = client.order_market_buy(symbol=TRADE_SYMBOL, quantity=f"{qty:.5f}")
                    executed_qty = float(order['executedQty'])
                    log_to_frontend(f"ORDEM DE COMPRA EXECUTADA: {executed_qty:.8f} BTC", 'success')
                    in_position = True
                    last_purchase_price = current_price
                    log_to_frontend(f"Stop-Loss definido em ${last_purchase_price * (1 - STOP_LOSS_PERCENTAGE):,.2f}", 'warn')
                    add_trade_to_history('compra', current_price, executed_qty)
                    update_portfolio_on_frontend()
                except Exception as e:
                    log_to_frontend(f"ERRO AO COMPRAR: {e}", 'error')

            # Sinal de Venda (Death Cross)
            elif prev_short_sma >= prev_long_sma and short_sma < long_sma and in_position:
                log_to_frontend(f"SINAL DE VENDA (Death Cross)! Tentando vender.", 'warn')
                try:
                    btc_balance_to_sell = float(client.get_asset_balance(asset='BTC')['free'])
                    if btc_balance_to_sell > 0.00001:
                        order = client.order_market_sell(symbol=TRADE_SYMBOL, quantity=f"{btc_balance_to_sell:.5f}")
                        executed_qty = float(order['executedQty'])
                        log_to_frontend(f"ORDEM DE VENDA EXECUTADA: {executed_qty:.8f} BTC", 'success')
                        in_position = False
                        last_purchase_price = 0
                        add_trade_to_history('venda', current_price, executed_qty)
                        update_portfolio_on_frontend()
                except Exception as e:
                    log_to_frontend(f"ERRO AO VENDER: {e}", 'error')
            
            time.sleep(60)

        except Exception as e:
            log_to_frontend(f"Erro CRÍTICO no loop da estratégia: {e}", 'error')
            time.sleep(60) # Adicionado para evitar loop infinito em caso de erro

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

    # LER AS CHAVES DO AMBIENTE DO SERVIDOR
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
    global is_bot_running, bot_thread, client
    if not is_bot_running: return
    log_to_frontend("A parar o bot...", 'warn')
    is_bot_running = False
    if bot_thread: bot_thread.join(timeout=10)
    client = None
    log_to_frontend("Bot parado com sucesso.", 'success')
    emit('bot_status', {'running': False})

@socketio.on('disconnect')
def handle_disconnect():
    print("Cliente desconectado!")

# --- CHATBOT ---
@socketio.on('send_chat_message')
def handle_chat_message(data):
    user_message = data['message'].lower().strip()
    emit('chat_response', {'sender': 'user', 'message': data['message']})
    
    time.sleep(1)
    bot_response = "Desculpe, não entendi o comando. Tente 'ajuda'."

    if 'ajuda' in user_message:
        bot_response = "Olá! Sou o seu agente. Pode perguntar sobre a 'estratégia' ou dar-me um comando como 'comprar 0.01 btc' ou 'vender 0.01 btc'."
    elif 'estratégia' in user_message:
        bot_response = "A estratégia ativa combina Crossover de Médias Móveis (SMA 20/50) com um Stop-Loss de 2% para proteção."
    
    elif user_message.startswith('comprar') or user_message.startswith('vender'):
        if not client or not is_bot_running:
            bot_response = "ERRO: O bot não está conectado à Binance. Conecte-se primeiro."
        else:
            parts = user_message.split()
            if len(parts) == 3:
                try:
                    action, qty_str, currency = parts
                    qty = float(qty_str)
                    
                    if currency.lower() != 'btc':
                        bot_response = "Comando inválido. Apenas a compra/venda de 'btc' é suportada."
                    else:
                        log_to_frontend(f"CHATBOT: Recebido comando para {action} {qty} BTC.", 'warn')
                        try:
                            if action == 'comprar':
                                order = client.order_market_buy(symbol='BTCUSDT', quantity=qty)
                            elif action == 'vender':
                                order = client.order_market_sell(symbol='BTCUSDT', quantity=qty)
                            
                            executed_qty = float(order['executedQty'])
                            avg_price = sum(float(f['price']) * float(f['qty']) for f in order['fills']) / executed_qty if executed_qty > 0 else 0
                            bot_response = f"SUCESSO! Ordem de {action} para {executed_qty:.8f} BTC executada."
                            log_to_frontend(bot_response, 'success')
                            
                            add_trade_to_history(action, avg_price, executed_qty)
                            update_portfolio_on_frontend()

                        except BinanceAPIException as e:
                            bot_response = f"ERRO DE API: {e.message}"
                            log_to_frontend(f"CHATBOT: Falha na ordem de {action}. Erro: {e.message}", 'error')
                        except Exception as e:
                            bot_response = f"Ocorreu um erro inesperado: {e}"
                            log_to_frontend(f"CHATBOT: Falha na ordem de {action}. Erro: {e}", 'error')
                
                except (ValueError, IndexError):
                     bot_response = "Formato de comando inválido. Use: 'comprar/vender [quantidade] btc'. Ex: 'comprar 0.01 btc'."
            else:
                 bot_response = "Formato de comando inválido. Use: 'comprar/vender [quantidade] btc'."

    emit('chat_response', {'sender': 'bot', 'message': bot_response})
