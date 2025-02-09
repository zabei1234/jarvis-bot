import os
import time
import logging
import requests
import traceback
import pandas as pd
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import ta

load_dotenv()

class TradeBot:
    def __init__(self):
        self.IS_TESTNET = False
        self.BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
        self.BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
        self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
        self.CHAT_ID = os.getenv("CHAT_ID")

        self.LEVERAGE = Decimal("10")
        self.BALANCE_ALLOCATION = Decimal("0.5")
        self.STOP_LOSS_PERCENT = Decimal("0.03")
        self.MAX_TRADES = 10
        self.RESERVE_PERCENT = Decimal("0.001")
        self.COMMISSION_RATE = Decimal("0.001")
        self.MAX_RETRIES = 3
        self.REDUCE_STEP = Decimal("0.9")
        self.REVERSAL_DROP = Decimal("0.005")
        self.ATR_STOP_MULTIPLIER = Decimal("1.2")
        self.HIGHER_TF = "5"
        self.HIGHER_TF_EMA_WINDOW = 50
        self.TP_PARTIAL_LEVEL = Decimal("0.01")
        self.TP_PARTIAL_SIZE = Decimal("0.5")

        self.client = HTTP(
            api_key=self.BYBIT_API_KEY,
            api_secret=self.BYBIT_API_SECRET,
            testnet=self.IS_TESTNET,
            timeout=30
        )
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.getLogger().addHandler(logging.FileHandler("trade_log.txt"))

        self.active_trades = {}
        self.symbols = [
            "BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "XRPUSDT",
            "JUPUSDT", "AEROUSDT", "JTOUSDT", "CFXUSDT", "TAOUSDT",
            "RAREUSDT", "LEVERUSDT", "MBOXUSDT", "EIGENUSDT", "FLRUSDT"
        ]

    def send_telegram_message(self, message):
        url = f"https://api.telegram.org/bot{self.TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": self.CHAT_ID, "text": message, "parse_mode": "HTML"}
        try:
            requests.post(url, data=data, timeout=10)
        except Exception:
            logging.error("Telegram send error")
            logging.error(traceback.format_exc())

    def get_balance(self):
        try:
            response = self.client.get_wallet_balance(accountType="UNIFIED")
            balance_info = response["result"]["list"][0]
            total_balance = Decimal(balance_info.get("totalWalletBalance", "0"))
            available_balance = Decimal(balance_info.get("availableBalance", str(total_balance)))
            used_margin = Decimal(balance_info.get("usedMargin", "0"))
            safe_balance = max(Decimal("0"), available_balance - (available_balance * self.RESERVE_PERCENT))
            logging.info(f"💰 Доступный баланс: {available_balance} USDT | "
                         f"Чистая маржа: {total_balance - used_margin} USDT | "
                         f"Используемая маржа: {used_margin} USDT | "
                         f"Реально доступно: {safe_balance} USDT")
            return total_balance, safe_balance
        except Exception:
            logging.error("Error getting balance")
            logging.error(traceback.format_exc())
            return Decimal("0"), Decimal("0")

    def get_trade_limits(self, symbol):
        try:
            response = self.client.get_instruments_info(category="linear", symbol=symbol)
            min_qty = Decimal(response["result"]["list"][0]["lotSizeFilter"]["minOrderQty"])
            step_size = Decimal(response["result"]["list"][0]["lotSizeFilter"]["qtyStep"])
            logging.info(f"🔍 {symbol} | Мин. объем: {min_qty}, Шаг: {step_size}")
            return min_qty, step_size
        except Exception:
            logging.error("Error getting trade limits")
            logging.error(traceback.format_exc())
            return Decimal("0"), Decimal("1")

    def round_step(self, value, step_size):
        multiplier = Decimal("1") / step_size
        return (Decimal(value) * multiplier // 1) / multiplier

    def get_ohlcv_data(self, symbol, interval="1", limit=200, start_time=None):
        try:
            params = {
                "category": "linear",
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
            if start_time is not None:
                params["from"] = start_time
            kline_data = self.client.get_kline(**params)
            if "result" not in kline_data or "list" not in kline_data["result"]:
                return pd.DataFrame()
            df = pd.DataFrame(kline_data["result"]["list"], columns=[
                "startTime", "open", "high", "low", "close", "volume", "turnover"
            ])
            df["startTime"] = pd.to_datetime(df["startTime"].astype(int), unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df.sort_values("startTime").reset_index(drop=True)
        except Exception:
            logging.error(f"Error fetching OHLCV for {symbol} interval {interval}")
            logging.error(traceback.format_exc())
            return pd.DataFrame()

    def calculate_indicators(self, df):
        if df.empty:
            return {}
        df["rsi"] = ta.momentum.rsi(df["close"], window=14)
        macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_hist"] = macd.macd_diff()
        stoch = ta.momentum.StochRSIIndicator(df["close"], window=14, smooth1=3, smooth2=3)
        df["stoch_k"] = stoch.stochrsi_k()
        df["stoch_d"] = stoch.stochrsi_d()
        df["ema_50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
        atr_indicator = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14)
        df["atr"] = atr_indicator.average_true_range()
        df["vol_ma"] = df["volume"].rolling(window=20).mean()
        latest = df.iloc[-1]
        return {
            "rsi": Decimal(str(latest["rsi"])),
            "macd_hist": Decimal(str(latest["macd_hist"])),
            "stoch_k": Decimal(str(latest["stoch_k"])),
            "stoch_d": Decimal(str(latest["stoch_d"])),
            "ema_50": Decimal(str(latest["ema_50"])),
            "atr": Decimal(str(latest["atr"])),
            "volume": Decimal(str(latest["volume"])),
            "vol_ma": Decimal(str(latest["vol_ma"])) if pd.notna(latest["vol_ma"]) else Decimal("0"),
            "last_open": Decimal(str(latest["open"])),
            "last_close": Decimal(str(latest["close"]))
        }

    def calculate_higher_tf_direction(self, symbol):
        df = self.get_ohlcv_data(symbol, interval=self.HIGHER_TF, limit=200)
        if df.empty or len(df) < self.HIGHER_TF_EMA_WINDOW:
            return None
        df["ema_higher"] = ta.trend.EMAIndicator(df["close"], window=self.HIGHER_TF_EMA_WINDOW).ema_indicator()
        last = df.iloc[-1]
        if last["close"] > last["ema_higher"]:
            return "up"
        elif last["close"] < last["ema_higher"]:
            return "down"
        return None

    def check_entry_conditions(self, symbol, indicators):
        vol_check = indicators.get("volume", Decimal("0")) >= indicators.get("vol_ma", Decimal("0")) * Decimal("0.2")
        if not vol_check:
            return None

        rsi_val = indicators.get("rsi", Decimal("50"))
        stoch_k_val = indicators.get("stoch_k", Decimal("50"))
        stoch_d_val = indicators.get("stoch_d", Decimal("50"))
        macd_hist = indicators.get("macd_hist", Decimal("0"))
        last_open = indicators.get("last_open", Decimal("0"))
        last_close = indicators.get("last_close", Decimal("0"))
        ema_50 = indicators.get("ema_50", Decimal("0"))
        higher_direction = self.calculate_higher_tf_direction(symbol)

        buy_cond = (
            rsi_val < Decimal("45") and
            stoch_k_val > stoch_d_val and
            macd_hist > 0 and
            last_close > last_open and
            last_close > ema_50 and
            higher_direction == "up"
        )
        sell_cond = (
            rsi_val > Decimal("60") and
            stoch_k_val < stoch_d_val and
            macd_hist < 0 and
            last_close < last_open and
            last_close < ema_50 and
            higher_direction == "down"
        )

        if buy_cond:
            return "Buy"
        elif sell_cond:
            return "Sell"
        return None

    def restore_active_trades(self):
        try:
            positions = self.client.get_positions(category="linear", settleCoin="USDT")
            if "result" in positions and "list" in positions["result"]:
                for pos in positions["result"]["list"]:
                    size = Decimal(pos["size"])
                    if size != 0:
                        symbol = pos["symbol"]
                        side = pos["side"]
                        entry_price = Decimal(pos["entryPrice"])
                        stop_loss = Decimal(pos.get("stopLoss", entry_price))
                        self.active_trades[symbol] = {
                            "side": side,
                            "entry_price": entry_price,
                            "qty": size,
                            "stop_loss": stop_loss,
                            "prev_price": entry_price,
                            "partial_tp_done": False
                        }
                        if side == "Buy":
                            self.active_trades[symbol]["highest_price"] = entry_price
                        else:
                            self.active_trades[symbol]["lowest_price"] = entry_price
        except Exception:
            logging.error("Error restoring active trades")
            logging.error(traceback.format_exc())

    def open_trade(self, symbol):
        if symbol in self.active_trades or len(self.active_trades) >= self.MAX_TRADES:
            return
        total_balance, safe_balance = self.get_balance()
        min_qty, step_size = self.get_trade_limits(symbol)

        df = self.get_ohlcv_data(symbol, interval="1", limit=200)
        indicators = self.calculate_indicators(df)
        side = self.check_entry_conditions(symbol, indicators)
        if not side:
            return

        trade_amount = (safe_balance * self.BALANCE_ALLOCATION) * self.LEVERAGE
        retries = 0
        while retries < self.MAX_RETRIES:
            try:
                required_margin = trade_amount / self.LEVERAGE
                if required_margin > safe_balance:
                    trade_amount *= self.REDUCE_STEP
                trade_amount -= trade_amount * self.COMMISSION_RATE
                trade_amount = self.round_step(trade_amount, step_size).quantize(step_size, rounding=ROUND_DOWN)
                if trade_amount < min_qty:
                    return
                price_data = self.client.get_tickers(category="linear", symbol=symbol)
                current_price = Decimal(price_data["result"]["list"][0]["lastPrice"])
                notional_value = trade_amount * current_price
                own_funds = notional_value / self.LEVERAGE
                borrowed_funds = notional_value - own_funds
                response = self.client.place_order(
                    category="linear",
                    symbol=symbol,
                    side=side,
                    orderType="Market",
                    qty=str(trade_amount),
                    reduceOnly=False
                )
                if "result" in response and "orderId" in response["result"]:
                    atr_val = indicators.get("atr", Decimal("0"))
                    if side == "Buy":
                        atr_stop = current_price - (atr_val * self.ATR_STOP_MULTIPLIER)
                        fixed_stop = current_price * (Decimal("1") - self.STOP_LOSS_PERCENT)
                        initial_stop = min(fixed_stop, atr_stop) if atr_val > 0 else fixed_stop
                    else:
                        atr_stop = current_price + (atr_val * self.ATR_STOP_MULTIPLIER)
                        fixed_stop = current_price * (Decimal("1") + self.STOP_LOSS_PERCENT)
                        initial_stop = max(fixed_stop, atr_stop) if atr_val > 0 else fixed_stop
                    try:
                        self.client.set_trading_stop(
                            category="linear",
                            symbol=symbol,
                            side=side,
                            positionIdx=0,
                            stopLoss=str(initial_stop)
                        )
                    except Exception:
                        logging.error("Error setting stop loss")
                        logging.error(traceback.format_exc())
                    self.active_trades[symbol] = {
                        "side": side,
                        "entry_price": current_price,
                        "own_funds": own_funds,
                        "borrowed_funds": borrowed_funds,
                        "notional": notional_value,
                        "qty": trade_amount,
                        "stop_loss": initial_stop,
                        "prev_price": current_price,
                        "partial_tp_done": False
                    }
                    if side == "Buy":
                        self.active_trades[symbol]["highest_price"] = current_price
                    else:
                        self.active_trades[symbol]["lowest_price"] = current_price
                    self.send_telegram_message(
                        f"✅ Открыта {side} сделка по {symbol}\n"
                        f"Объём: {notional_value:.2f} USDT\n"
                        f"Собственные: {own_funds:.2f} USDT\n"
                        f"Заёмные: {borrowed_funds:.2f} USDT\n"
                        f"Цена входа: {current_price}\n"
                        f"Стоп-лосс: {initial_stop}"
                    )
                    return
            except Exception:
                logging.error("Error placing order")
                logging.error(traceback.format_exc())
            retries += 1
            trade_amount *= self.REDUCE_STEP
            time.sleep(1)

    def partial_close_trade(self, symbol, fraction=None):
        if symbol not in self.active_trades:
            return
        fraction = fraction or self.TP_PARTIAL_SIZE
        info = self.active_trades[symbol]
        old_qty = info["qty"]
        close_qty = old_qty * fraction
        if close_qty < Decimal("1"):
            return
        side = "Sell" if info["side"] == "Buy" else "Buy"
        try:
            self.client.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(close_qty.quantize(Decimal("1"), rounding=ROUND_DOWN)),
                reduceOnly=True
            )
            self.active_trades[symbol]["qty"] = old_qty - close_qty
            self.active_trades[symbol]["partial_tp_done"] = True
            self.send_telegram_message(f"⚙ Частичное закрытие {symbol}: {fraction * 100}% позиции.")
        except Exception:
            logging.error("Error in partial close")
            logging.error(traceback.format_exc())

    def close_trade(self, symbol):
        if symbol not in self.active_trades:
            return
        try:
            price_data = self.client.get_tickers(category="linear", symbol=symbol)
            exit_price = Decimal(price_data["result"]["list"][0]["lastPrice"])
            side = self.active_trades[symbol]["side"]
            entry_price = self.active_trades[symbol]["entry_price"]
            trade_qty = self.active_trades[symbol]["qty"]
            profit = (exit_price - entry_price) * trade_qty if side == "Buy" else (entry_price - exit_price) * trade_qty
            total_balance, _ = self.get_balance()
            self.send_telegram_message(
                f"❎ Закрыта сделка по {symbol}\n"
                f"Цена входа: {entry_price}\n"
                f"Цена выхода: {exit_price}\n"
                f"Прибыль (монет): {profit:.4f}\n"
                f"Текущий баланс: {total_balance:.2f} USDT"
            )
            del self.active_trades[symbol]
        except Exception:
            logging.error("Error closing trade")
            logging.error(traceback.format_exc())

    def monitor_positions(self):
        try:
            positions = self.client.get_positions(category="linear", settleCoin="USDT")
            if "result" in positions and "list" in positions["result"]:
                for pos in positions["result"]["list"]:
                    sym = pos["symbol"]
                    size = Decimal(pos["size"])
                    if sym in self.active_trades and size == 0:
                        self.close_trade(sym)
        except Exception:
            logging.error("Error monitoring positions")
            logging.error(traceback.format_exc())

    def update_trailing_stops(self):
        for symbol, trade_info in list(self.active_trades.items()):
            side = trade_info["side"]
            try:
                price_data = self.client.get_tickers(category="linear", symbol=symbol)
                current_price = Decimal(price_data["result"]["list"][0]["lastPrice"])
                entry_price = trade_info["entry_price"]
                current_stop = trade_info.get("stop_loss", entry_price)
                prev_price = trade_info.get("prev_price", current_price)

                if side == "Buy":
                    if current_price <= current_stop:
                        self.close_trade(symbol)
                        continue
                    current_profit_pct = (current_price / entry_price - Decimal("1")) * Decimal("100")
                    if not trade_info["partial_tp_done"] and current_profit_pct >= self.TP_PARTIAL_LEVEL * Decimal("100"):
                        self.partial_close_trade(symbol, self.TP_PARTIAL_SIZE)
                    if "highest_price" in trade_info and current_price > trade_info["highest_price"]:
                        self.active_trades[symbol]["highest_price"] = current_price
                    if current_profit_pct > 0 and current_price < prev_price * (Decimal("1") - self.REVERSAL_DROP):
                        self.close_trade(symbol)
                        continue
                else:
                    if current_price >= current_stop:
                        self.close_trade(symbol)
                        continue
                    current_profit_pct = (entry_price / current_price - Decimal("1")) * Decimal("100")
                    if not trade_info["partial_tp_done"] and current_profit_pct >= self.TP_PARTIAL_LEVEL * Decimal("100"):
                        self.partial_close_trade(symbol, self.TP_PARTIAL_SIZE)
                    if "lowest_price" in trade_info and current_price < trade_info["lowest_price"]:
                        self.active_trades[symbol]["lowest_price"] = current_price
                    if current_profit_pct > 0 and current_price > prev_price * (Decimal("1") + self.REVERSAL_DROP):
                        self.close_trade(symbol)
                        continue
                self.active_trades[symbol]["prev_price"] = current_price
            except Exception:
                logging.error(f"Error updating trailing stop for {symbol}")
                logging.error(traceback.format_exc())

    def run(self):
        try:
            self.restore_active_trades()
            self.send_telegram_message("🚀 Бот запущен!")
            while True:
                try:
                    for symbol in self.symbols:
                        self.open_trade(symbol)
                        time.sleep(1)
                    self.update_trailing_stops()
                    self.monitor_positions()
                except Exception:
                    logging.error("Error in main loop iteration")
                    logging.error(traceback.format_exc())
                    time.sleep(30)
                time.sleep(5)
        except Exception:
            logging.error("Error running bot")
            logging.error(traceback.format_exc())

if __name__ == "__main__":
    bot = TradeBot()
    bot.run()
