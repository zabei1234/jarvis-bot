import requests
from pybit.unified_trading import HTTP
from telegram import Bot
from telegram.ext import Application
import logging
import time
import numpy as np
import asyncio
import socket

# Логирование
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()  # Добавляем вывод логов в терминал
    ]
)

# Конфигурация
TELEGRAM_TOKEN = '8153580145:AAED83h9IodTvOH3DmrdPjsinS9K94nSEk0'
CHAT_ID = '1330519186'
BYBIT_API_KEY = 'TUBkHXS7hyF8Y9i1hJ'
BYBIT_API_SECRET = 'K1dlpR4sO6MVSjnkML1noQYTcD9vq4QdstDU'

# Инициализация клиентов
app = Application.builder().token(TELEGRAM_TOKEN).build()
client = HTTP(api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET, recv_window=5000, timeout=30)
MIN_TRADE_QTY = 0.01  # Минимально допустимый объём сделки для ETHUSDT
MIN_TRADE_BALANCE = 10  # Минимальный баланс для торговли в USDT

# Параметры управления рисками
STOP_LOSS_PERCENT = 2  # Уровень стоп-лосса в процентах
TAKE_PROFIT_PERCENT = 10  # Уровень тейк-профита в процентах

# Список символов для анализа
SYMBOLS_TO_TRADE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]

# Логирование текущего IP
try:
    current_ip = socket.gethostbyname(socket.gethostname())
    logging.info(f"IP-адрес бота: {current_ip}")
except Exception as e:
    logging.error(f"Ошибка определения IP-адреса: {e}")

# Флаг для отслеживания состояния
last_message = None

async def send_telegram_message(message):
    global last_message
    try:
        # Отправляем сообщение только если оно отличается от предыдущего
        if message != last_message:
            await app.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='HTML')
            logging.info(f"Telegram message sent: {message}")
            last_message = message
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения в Telegram: {e}")

# Форматирование сообщения для Telegram
def format_balance_message(usdt_balance):
    return (
        f"<b>Текущий баланс:</b>\n"
        f"<b>USDT:</b> {usdt_balance:.2f}\n"
        f"<b>Минимальный баланс для торговли:</b> {MIN_TRADE_BALANCE} USDT"
    )

def format_trade_message(symbol, side, qty, price):
    return (
        f"<b>Сделка совершена:</b>\n"
        f"<b>Символ:</b> {symbol}\n"
        f"<b>Тип:</b> {'Лонг' if side == 'Buy' else 'Шорт'}\n"
        f"<b>Объём:</b> {qty}\n"
        f"<b>Цена входа:</b> {price:.2f}"
    )

# Расчёт RSI
def calculate_rsi(closes, period=14):
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down > 0 else float('inf')
    rsi = np.zeros_like(closes)
    rsi[:period] = 100 - 100 / (1 + rs)
    for i in range(period, len(closes)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0
        else:
            upval = 0
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down > 0 else float('inf')
        rsi[i] = 100 - 100 / (1 + rs)
    return rsi[-1]

# Расчёт MACD
def calculate_macd(closes, short_period=12, long_period=26, signal_period=9):
    short_ema = np.convolve(closes, np.ones(short_period) / short_period, mode='valid')
    long_ema = np.convolve(closes, np.ones(long_period) / short_period, mode='valid')
    macd_line = short_ema[-len(long_ema):] - long_ema
    signal_line = np.convolve(macd_line, np.ones(signal_period) / short_period, mode='valid')
    return macd_line[-1], signal_line[-1]

# Расчёт Bollinger Bands
def calculate_bollinger_bands(closes, period=20, num_std_dev=2):
    sma = np.convolve(closes, np.ones(period) / period, mode='valid')
    std_dev = np.std(closes[-period:])
    upper_band = sma[-1] + (num_std_dev * std_dev)
    lower_band = sma[-1] - (num_std_dev * std_dev)
    return upper_band, lower_band

# Расчёт ATR
def calculate_atr(highs, lows, closes, period=14):
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])))
    atr = np.convolve(tr, np.ones(period) / period, mode='valid')
    return atr[-1]

# Анализ рынка с несколькими индикаторами
def analyze_market(symbol):
    try:
        response = client.get_kline(category="linear", symbol=symbol, interval="15", limit=50)
        candles = response.get("result", {}).get("list", [])
        if not candles:
            logging.warning(f"Нет данных свечей для {symbol}.")
            return None

        closes = np.array([float(c[4]) for c in candles])
        highs = np.array([float(c[2]) for c in candles])
        lows = np.array([float(c[3]) for c in candles])

        rsi = calculate_rsi(closes)
        macd, signal = calculate_macd(closes)
        upper_band, lower_band = calculate_bollinger_bands(closes)
        atr = calculate_atr(highs, lows, closes)

        logging.info(
            f"Анализ {symbol}: RSI={rsi:.2f}, MACD={macd:.2f}, Signal={signal:.2f}, "
            f"Upper BB={upper_band:.2f}, Lower BB={lower_band:.2f}, ATR={atr:.2f}"
        )
        return rsi, macd, signal, upper_band, lower_band, atr
    except Exception as e:
        logging.error(f"Ошибка анализа рынка для {symbol}: {e}")
        return None

# Открытие сделки с управлением рисками
def open_trade_with_risk_management(symbol, side, qty, entry_price):
    stop_loss_price = entry_price * (1 - STOP_LOSS_PERCENT / 100) if side == "Buy" else entry_price * (1 + STOP_LOSS_PERCENT / 100)
    take_profit_price = entry_price * (1 + TAKE_PROFIT_PERCENT / 100) if side == "Buy" else entry_price * (1 - TAKE_PROFIT_PERCENT / 100)

    try:
        response = client.place_active_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            timeInForce="GoodTillCancel",
            stopLoss=str(stop_loss_price),
            takeProfit=str(take_profit_price)
        )
        logging.info(f"Сделка с управлением рисками открыта: {response}")
    except Exception as e:
        logging.error(f"Ошибка открытия сделки с управлением рисками для {symbol}: {e}")

# Основной цикл
async def run_bot():
    while True:
        try:
            logging.info("Запуск торговой логики.")
            response = client.get_wallet_balance(accountType="UNIFIED")
            balances = response.get("result", {}).get("list", [])[0].get("coin", [])

            usdt_balance = None
            for coin in balances:
                if coin.get("coin") == "USDT":
                    try:
                        usdt_balance = float(coin.get("walletBalance", 0))
                        break
                    except ValueError:
                        logging.error("Ошибка преобразования баланса USDT в число.")

            if usdt_balance is None:
                logging.warning("Не удалось получить баланс USDT.")
                await send_telegram_message("Ошибка получения баланса USDT.")
                continue

            await send_telegram_message(format_balance_message(usdt_balance))

            if usdt_balance < MIN_TRADE_BALANCE:
                logging.warning("Недостаточный баланс для торговли.")
                await send_telegram_message("Недостаточный баланс для торговли.")
                continue

            for symbol in SYMBOLS_TO_TRADE:
                market_data = analyze_market(symbol)
                if market_data is None:
                    continue

                rsi, macd, signal, upper_band, lower_band, atr = market_data

                if rsi < 30 and macd < signal and lower_band:
                    qty = round(MIN_TRADE_QTY, 2)
                    entry_price = float(client.get_ticker(symbol=symbol)["result"]["lastPrice"])
                    open_trade_with_risk_management(symbol, "Buy", qty, entry_price)
                    await send_telegram_message(format_trade_message(symbol, "Buy", qty, entry_price))
                elif rsi > 70 and macd > signal and upper_band:
                    qty = round(MIN_TRADE_QTY, 2)
                    entry_price = float(client.get_ticker(symbol=symbol)["result"]["lastPrice"])
                    open_trade_with_risk_management(symbol, "Sell", qty, entry_price)
                    await send_telegram_message(format_trade_message(symbol, "Sell", qty, entry_price))

        except Exception as e:
            logging.error(f"Ошибка в основном цикле: {e}")
        finally:
            await asyncio.sleep(60)  # Задержка в 60 секунд перед следующей итерацией

# Запуск бота
if __name__ == "__main__":
    asyncio.run(run_bot())