import argparse
import logging
import os
import time
from pathlib import Path

import ccxt
import pandas as pd
import telebot
from colorama import Fore, Style
from rich.live import Live
from rich.table import Table

import tylerapi
from config import load_config

from util import tables

# 1. Create config.json from config.json.example
# 2. Enter exchange_api_key and exchange_api_secret
# 3. Check/fill all other options. For telegram see below

# 1. Get token from botfather after creating new bot, send a message to your new bot
# 2. Go to https://api.telegram.org/bot<bot_token>/getUpdates
# 3. Replacing <bot_token> with your token from the botfather after creating new bot
# 4. Look for chat id and copy the chat id into config.json

log = logging.getLogger(__name__)

def sendmessage(message):
    bot.send_message(config.telegram_chat_id, message)


# Bools
version = "Directional Scalper v1.1.1"
long_mode = False
short_mode = False
hedge_mode = False
aggressive_mode = False
btclinear_long_mode = False
btclinear_short_mode = False
deleveraging_mode = False
longbias_mode = False
violent_mode = False
high_vol_stack_mode = False
leverage_verified = False
tg_notifications = False

print(Fore.LIGHTCYAN_EX + "", version, "connecting to exchange" + Style.RESET_ALL)

dex_balance, dex_pnl, dex_upnl, dex_wallet, dex_equity = 0, 0, 0, 0, 0
(
    long_pos_qty,
    short_pos_qty,
    long_pos_price,
    long_liq_price,
    short_pos_price,
    short_liq_price,
) = (0, 0, 0, 0, 0, 0)

parser = argparse.ArgumentParser(description="Scalper supports 5 modes")

parser.add_argument(
    "--mode",
    type=str,
    help="Mode to use",
    choices=["long", "short", "hedge", "aggressive", "longbias", "btclinear-long", "btclinear-short", "violent"],
    required=True,
)

parser.add_argument("--symbol", type=str, help="Specify symbol", required=True)

parser.add_argument("--iqty", type=str, help="Initial entry quantity", required=True)

parser.add_argument("--deleverage", type=str, help="Deleveraging enabled", choices=["on", "off"], required=False)

parser.add_argument("--avoidfees", type=str, help="Avoid all fees", choices=["on", "off"], required=False)

# parser.add_arguemnt("--violent", type=str, help="Violent mode", choices=["on", "off"], required=False)

parser.add_argument(
    "--tg", type=str, help="TG Notifications", choices=["on", "off"], required=True
)

parser.add_argument(
    "--config", type=str, help="Config file. Example: my_config.json", required=False
)

args = parser.parse_args()

if args.mode == "long":
    long_mode = True
elif args.mode == "short":
    short_mode = True
elif args.mode == "hedge":
    hedge_mode = True
elif args.mode == "aggressive":
    aggressive_mode = True
elif args.mode == "longbias":
    longbias_mode = True
elif args.mode == "btclinear-long":
    btclinear_long_mode = True
elif args.mode == "btclinear-short":
    btclinear_short_mode = True
elif args.mode == "violent":
    violent_mode = True


if args.symbol:
    symbol = args.symbol
else:
    symbol = input("Instrument undefined. \nInput instrument:")

if args.iqty:
    trade_qty = args.iqty
else:
    trade_qty = input("Lot size:")

if args.tg == "on":
    tg_notifications = True

if args.deleverage == "on":
    deleveraging_mode = True
else:
    deleveraging_mode = False


config_file = "config.json"
if args.config:
    config_file = args.config

# Load config
print("Loading config: " + config_file)
config_file = Path(Path().resolve(), config_file)
config = load_config(path=config_file)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=os.environ.get("LOGLEVEL", "INFO"),
)

if args.avoidfees == "on":
    config.avoid_fees = True
    print("Avoiding fees")

if tg_notifications:
    bot = telebot.TeleBot(config.telegram_api_token, parse_mode=None)

    @bot.message_handler(commands=["start", "help"])
    def send_welcome(message):
        bot.reply_to(message, "Howdy, how are you doing?")

    @bot.message_handler(func=lambda message: True)
    def echo_all(message):
        bot.reply_to(message, message.text)

min_volume = config.min_volume
min_distance = config.min_distance
botname = config.bot_name
linear_taker_fee = config.linear_taker_fee
wallet_exposure = config.wallet_exposure

exchange = ccxt.bybit(
    {
        "enableRateLimit": True,
        "apiKey": config.exchange_api_key,
        "secret": config.exchange_api_secret,
    }
)

# Functions


# Get min vol & spread data from API
def get_min_vol_dist_data(symbol) -> bool:
    try:
        tylerapi.grab_api_data()
        spread5m = tylerapi.get_asset_5m_spread(symbol, tylerapi.grab_api_data())
        volume1m = tylerapi.get_asset_volume_1m_1x(symbol, tylerapi.grab_api_data())

        return volume1m > min_volume and spread5m > min_distance
    except Exception as e:
        log.warning(f"{e}")
        return False


# get_1m_data() [0]3 high, [1]3 low, [2]6 high, [3]6 low, [4]10 vol
def get_1m_data():
    try: 
        timeframe = "1m"
        num_bars = 20
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=num_bars)
        df = pd.DataFrame(bars, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
        df["Time"] = pd.to_datetime(df["Time"], unit="ms")
        df["MA_3_High"] = df.High.rolling(3).mean()
        df["MA_3_Low"] = df.Low.rolling(3).mean()
        df["MA_6_High"] = df.High.rolling(6).mean()
        df["MA_6_Low"] = df.Low.rolling(6).mean()
        get_1m_data_3_high = df["MA_3_High"].iat[-1]
        get_1m_data_3_low = df["MA_3_Low"].iat[-1]
        get_1m_data_6_high = df["MA_6_High"].iat[-1]
        get_1m_data_6_low = df["MA_6_Low"].iat[-1]
        return get_1m_data_3_high, get_1m_data_3_low, get_1m_data_6_high, get_1m_data_6_low
    except Exception as e:
        log.warning(f"{e}")



# get_5m_data() [0]3 high, [1]3 low, [2]6 high, [3]6 low
def get_5m_data():
    try:
        timeframe = "5m"
        num_bars = 20
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=num_bars)
        df = pd.DataFrame(bars, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
        df["Time"] = pd.to_datetime(df["Time"], unit="ms")
        df["MA_3_High"] = df.High.rolling(3).mean()
        df["MA_3_Low"] = df.Low.rolling(3).mean()
        df["MA_6_High"] = df.High.rolling(6).mean()
        df["MA_6_Low"] = df.Low.rolling(6).mean()
        get_5m_data_3_high = df["MA_3_High"].iat[-1]
        get_5m_data_3_low = df["MA_3_Low"].iat[-1]
        get_5m_data_6_high = df["MA_6_High"].iat[-1]
        get_5m_data_6_low = df["MA_6_Low"].iat[-1]
        return get_5m_data_3_high, get_5m_data_3_low, get_5m_data_6_high, get_5m_data_6_low
    except Exception as e:
        log.warning(f"{e}")


def get_balance():
    global dex_balance, dex_pnl, dex_upnl, dex_wallet, dex_equity
    try:
        dex = exchange.fetch_balance()["info"]["result"]
        dex_balance = dex["USDT"]["available_balance"]
        dex_pnl = dex["USDT"]["realised_pnl"]
        dex_upnl = dex["USDT"]["unrealised_pnl"]
        dex_wallet = round(float(dex["USDT"]["wallet_balance"]), 2)
        dex_equity = round(float(dex["USDT"]["equity"]), 2)
    except KeyError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unknown error occured in get_balance(): {e}")
        log.warning(f"{e}")


# get_orderbook() [0]bid, [1]ask
def get_orderbook():
    try:      
        ob = exchange.fetch_order_book(symbol)
        bid = ob["bids"][0][0]
        ask = ob["asks"][0][0]
        return bid, ask
    except:
        pass


# get_market_data() [0]precision, [1]leverage, [2]min_trade_qty
def get_market_data():
    try:
        global leverage
        exchange.load_markets()
        precision = exchange.market(symbol)["info"]["price_scale"]
        leverage = exchange.market(symbol)["info"]["leverage_filter"]["max_leverage"]
        min_trade_qty = exchange.market(symbol)["info"]["lot_size_filter"][
            "min_trading_qty"
        ]
        return precision, leverage, min_trade_qty
    except:
        pass


def get_short_positions():
    try:
        global short_pos_qty, short_pos_price, short_symbol_realised, short_symbol_cum_realised, short_pos_unpl, short_pos_unpl_pct, short_liq_price
        pos_dict = exchange.fetch_positions([symbol])
        pos_dict = pos_dict[1]
        short_pos_qty = float(pos_dict["contracts"])
        short_symbol_realised = round(float(pos_dict["info"]["realised_pnl"] or 0), 2)
        short_symbol_cum_realised = round(
            float(pos_dict["info"]["cum_realised_pnl"] or 0), 2
        )
        short_pos_unpl = round(float(pos_dict["info"]["unrealised_pnl"] or 0), 2)
        short_pos_unpl_pct = round(float(pos_dict["percentage"] or 0), 2)
        short_pos_price = pos_dict["entryPrice"] or 0
        short_liq_price = pos_dict["liquidationPrice"] or 0
    except Exception as e:
        log.warning(f"{e}")

def get_long_positions():
    try:
        global long_pos_qty, long_pos_price, long_symbol_realised, long_symbol_cum_realised, long_pos_unpl, long_pos_unpl_pct, long_liq_price
        pos_dict = exchange.fetch_positions(
            [symbol]
        )  # TODO: We can fetch it just once to save some API time
        pos_dict = pos_dict[0]
        long_pos_qty = float(pos_dict["contracts"])
        long_symbol_realised = round(float(pos_dict["info"]["realised_pnl"]), 2)
        long_symbol_cum_realised = round(float(pos_dict["info"]["cum_realised_pnl"]), 2)
        long_pos_unpl = float(pos_dict["info"]["unrealised_pnl"] or 0)
        long_pos_unpl_pct = round(float(pos_dict["percentage"] or 0), 2)
        long_pos_price = pos_dict["entryPrice"] or 0
        long_liq_price = pos_dict["liquidationPrice"] or 0
    except Exception as e:
        log.warning(f"{e}")


# get_open_orders() [0]order_id, [1]order_price, [2]order_qty
def get_open_orders():
    try:
        order = exchange.fetch_open_orders(symbol)
        order_status = order[0]["info"]["order_status"]
        order_side = order[0]["info"]["side"]
        reduce_only = order[0]["info"]["reduce_only"]
        if (
            order_status == "New"
            and order_status != "Filled"
            and order_side == "Buy"
            and reduce_only
        ):
            order_id = order[0]["info"]["order_id"]
            order_price = order[0]["info"]["price"]
            order_qty = order[0]["info"]["qty"]
        else:
            return 0, 0, 0
        return order_id, order_price, order_qty
    except Exception as e:
        log.warning(f"{e}")


def cancel_entry():
    try:
        order = exchange.fetch_open_orders(symbol)
        order_id = order[0]["info"]["order_id"]
        order_status = order[0]["info"]["order_status"]
        order_side = order[0]["info"]["side"]
        reduce_only = order[0]["info"]["reduce_only"]
        if (
            order_status != "Filled"
            and order_side == "Buy"
            and order_status != "Cancelled"
            and not reduce_only
        ):
            exchange.cancel_order(symbol=symbol, id=order_id)
        elif (
            order_status != "Filled"
            and order_side == "Sell"
            and order_status != "Cancelled"
            and not reduce_only
        ):
            exchange.cancel_order(symbol=symbol, id=order_id)
    except Exception as e:
        log.warning(f"{e}")

def cancel_close():
    try:
        order = exchange.fetch_open_orders(symbol)
        order_id = order[0]["info"]["order_id"]
        order_status = order[0]["info"]["order_status"]
        order_side = order[0]["info"]["side"]
        reduce_only = order[0]["info"]["reduce_only"]
        if (
            order_status != "Filled"
            and order_side == "Buy"
            and order_status != "Cancelled"
            and reduce_only
        ):
            exchange.cancel_order(symbol=symbol, id=order_id)
        elif (
            order_status != "Filled"
            and order_side == "Sell"
            and order_status != "Cancelled"
            and reduce_only
        ):
            exchange.cancel_order(symbol=symbol, id=order_id)
    except Exception as e:
        log.warning(f"{e}")


def short_trade_condition():
    short_trade_condition = get_orderbook()[0] > get_1m_data()[0]
    return short_trade_condition


def long_trade_condition():
    long_trade_condition = get_orderbook()[0] < get_1m_data()[0]
    return long_trade_condition


def add_short_trade_condition():
    add_short_trade_condition = short_pos_price < get_1m_data()[3]
    return add_short_trade_condition


def add_long_trade_condition():
    add_long_trade_condition = long_pos_price > get_1m_data()[3]
    return add_long_trade_condition


def leverage_verification(symbol):
    try:
        exchange.set_position_mode(hedged="BothSide", symbol=symbol)
        print(
            Fore.LIGHTYELLOW_EX + "Position mode changed to BothSide" + Style.RESET_ALL
        )
    except Exception as e:
        print(Fore.YELLOW + "Position mode unchanged" + Style.RESET_ALL)
        #log.warning(f"{e}")
    # Set margin mode
    try:
        exchange.set_margin_mode(marginMode="cross", symbol=symbol)
        print(Fore.LIGHTYELLOW_EX + "Margin mode set to cross" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.YELLOW + "Margin mode unchanged" + Style.RESET_ALL)
        #log.warning(f"{e}")
    # Set leverage
    try:
        exchange.set_leverage(leverage=get_market_data()[1], symbol=symbol)
        print(Fore.YELLOW + "Leverage set" + Style.RESET_ALL)
    except Exception as e:
        print(
            Fore.YELLOW + "Leverage not modified, current leverage is",
            get_market_data()[1],
        )
        #log.warning(f"{e}")


if not leverage_verified:
    try:
        leverage_verification(symbol)
    except KeyError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unknown error occured in leverage verification: {e}")
        log.warning(f"{e}")

get_balance()

# max_trade_qty = round(
#     (float(dex_equity) / float(get_orderbook()[1]))
#     / (100 / float(get_market_data()[1])),
#     int(float(get_market_data()[2])),
# )

# Implement basic wallet exposure

max_trade_qty = round(
    (float(dex_equity) * wallet_exposure / float(get_orderbook()[1]))
    / (100 / float(get_market_data()[1])),
    int(float(get_market_data()[2])),
)

violent_max_trade_qty = max_trade_qty * 5

current_leverage = get_market_data()[1]

print(f"Min Trade Qty: {get_market_data()[2]}")
print(Fore.LIGHTYELLOW_EX + "1x:", max_trade_qty, " ")
print(
    Fore.LIGHTCYAN_EX + "0.01x ",
    round(max_trade_qty / 100, int(float(get_market_data()[2]))),
    "",
)
print(f"0.005x : {round(max_trade_qty / 200, int(float(get_market_data()[2])))}")
print(f"0.001x : {round(max_trade_qty / 500, int(float(get_market_data()[2])))}")

# Fix for the first run when variable is not yet assigned
short_symbol_cum_realised = 0
short_symbol_realised = 0
short_pos_unpl = 0
short_pos_unpl_pct = 0

long_symbol_cum_realised = 0
long_symbol_realised = 0
long_pos_unpl = 0
long_pos_unpl_pct = 0

# Define Tyler API Func for ease of use later on
# Should turn these into functions and reduce calls

vol_condition_true = get_min_vol_dist_data(symbol)
tyler_total_volume_1m = tylerapi.get_asset_total_volume_1m(
    symbol, tylerapi.grab_api_data()
)
tyler_total_volume_5m = tylerapi.get_asset_total_volume_5m(
    symbol, tylerapi.grab_api_data()
)
# tyler_1x_volume_1m = tylerapi.get_asset_volume_1m_1x(symbol, tylerapi.grab_api_data())
tyler_1x_volume_5m = tylerapi.get_asset_volume_1m_1x(symbol, tylerapi.grab_api_data())
# tyler_5m_spread = tylerapi.get_asset_5m_spread(symbol, tylerapi.grab_api_data())
tyler_1m_spread = tylerapi.get_asset_1m_spread(symbol, tylerapi.grab_api_data())


# tyler_trend = tylerapi.get_asset_trend(symbol, tylerapi.grab_api_data())


def find_trend():
    try:
        tylerapi.grab_api_data()
        tyler_trend = tylerapi.get_asset_trend(symbol, tylerapi.grab_api_data())

        return tyler_trend
    except:
        pass


def find_1m_spread():
    try:
        tylerapi.grab_api_data()
        tyler_1m_spread = tylerapi.get_asset_1m_spread(symbol, tylerapi.grab_api_data())

        return tyler_1m_spread
    except:
        pass


def find_5m_spread():
    try:
        tylerapi.grab_api_data()
        tyler_spread = tylerapi.get_asset_5m_spread(symbol, tylerapi.grab_api_data())

        return tyler_spread
    except:
        pass


def find_1m_1x_volume():
    try:
        tylerapi.grab_api_data()
        tyler_1x_volume_1m = tylerapi.get_asset_volume_1m_1x(
            symbol, tylerapi.grab_api_data()
        )
        return tyler_1x_volume_1m
    except:
        pass


def find_mode():
    mode = args.mode

    return mode


try:
    get_short_positions()
    get_long_positions()
except:
    pass


# Long entry logic if long enabled
def initial_long_entry(current_bid):
    if (
        # long_mode
        long_trade_condition()
        and find_1m_1x_volume() > min_volume
        and find_5m_spread() > min_distance
        and long_pos_qty == 0
        and long_pos_qty < max_trade_qty
        and find_trend() == "long"
    ):
        try:
            exchange.create_limit_buy_order(symbol, trade_qty, current_bid)
            time.sleep(0.01)
        except Exception as e:
            log.warning(f"{e}")
    else:
        pass

def initial_long_entry_linear_btc(current_bid):
    if (
        # long_mode
        long_trade_condition()
        and find_1m_1x_volume() > min_volume
        and find_5m_spread() > min_distance
        and long_pos_qty == 0
        and find_trend() == "long"
    ):
        try:
            exchange.create_limit_buy_order(symbol, trade_qty, current_bid)
            time.sleep(0.01)
        except Exception as e:
            log.warning(f"{e}")
    else:
        pass

# Short entry logic if short enabled
def initial_short_entry_linear_btc(current_ask):
    if (
        # short_mode
        short_trade_condition()
        and find_1m_1x_volume() > min_volume
        and find_5m_spread() > min_distance
        and short_pos_qty == 0
        and find_trend() == "short"
    ):
        try:
            exchange.create_limit_sell_order(symbol, trade_qty, current_ask)
            time.sleep(0.01)
        except Exception as e:
            log.warning(f"{e}")
    else:
        pass


# Short entry logic if short enabled
def initial_short_entry(current_ask):
    if (
        # short_mode
        short_trade_condition()
        and find_1m_1x_volume() > min_volume
        and find_5m_spread() > min_distance
        and short_pos_qty == 0
        and short_pos_qty < max_trade_qty
        and find_trend() == "short"
    ):
        try:
            exchange.create_limit_sell_order(symbol, trade_qty, current_ask)
            time.sleep(0.01)
        except Exception as e:
            log.warning(f"{e}")
    else:
        pass

def get_current_price(exchange, symbol):
    ticker = exchange.fetch_ticker(symbol)
    current_price = (ticker['bid'] + ticker['ask']) / 2
    return current_price

# Calculate for fees
def calculate_min_price_increment(pos_price, taker_fee_rate):
    return pos_price * taker_fee_rate * 2

def calculate_long_profit_prices_avoidfees(long_pos_price, price_difference, price_scale, min_price_increment, taker_fee_rate, long_order_value):
    long_profit_prices = []
    profit_multipliers = [min_price_increment * 2, min_price_increment * 4, min_price_increment * 6]
    for multiplier in profit_multipliers:
        profit_price = long_pos_price + (price_difference * multiplier)
        rounded_profit_price = round(profit_price, price_scale)
        if multiplier == min_price_increment * 2:
            fees = long_order_value * taker_fee_rate
            if (rounded_profit_price - long_pos_price) * long_order_value <= fees:
                rounded_profit_price += min_price_increment
        long_profit_prices.append(rounded_profit_price)
    return long_profit_prices


def calculate_short_profit_prices_avoidfees(short_pos_price, price_difference, price_scale, min_price_increment, taker_fee_rate, short_order_value):
    short_profit_prices = []
    profit_multipliers = [min_price_increment * 2, min_price_increment * 4, min_price_increment * 6]
    for multiplier in profit_multipliers:
        profit_price = short_pos_price - (price_difference * multiplier)
        rounded_profit_price = round(profit_price, price_scale)
        if multiplier == min_price_increment * 2:
            fees = short_order_value * taker_fee_rate
            if (short_pos_price - rounded_profit_price) * short_order_value <= fees:
                rounded_profit_price -= min_price_increment
        short_profit_prices.append(rounded_profit_price)
    return short_profit_prices

def calculate_long_profit_prices(long_pos_price, price_difference, price_scale):
    try:
        long_profit_prices = []
        profit_multipliers = [0.3, 0.6, 1.0]
        for multiplier in profit_multipliers:
            profit_price = long_pos_price + (price_difference * multiplier)
            long_profit_prices.append(round(profit_price, price_scale))
        return long_profit_prices
    except:
        pass

def calculate_short_profit_prices(short_pos_price, price_difference, price_scale):
    short_profit_prices = []
    profit_multipliers = [0.3, 0.6, 1.0]
    for multiplier in profit_multipliers:
        profit_price = short_pos_price - (price_difference * multiplier)
        short_profit_prices.append(round(profit_price, price_scale))
    return short_profit_prices


def generate_main_table():
    try:
        min_vol_dist_data = get_min_vol_dist_data(symbol)
        mode = find_mode()
        trend = find_trend()
        market_data = get_market_data()
        return tables.generate_main_table(version, short_pos_unpl, long_pos_unpl, short_pos_unpl_pct, long_pos_unpl_pct, symbol, dex_wallet, 
                            dex_equity, short_symbol_cum_realised, long_symbol_realised, short_symbol_realised,
                            trade_qty, long_pos_qty, short_pos_qty, long_pos_price, long_liq_price, short_pos_price, 
                            short_liq_price, max_trade_qty, market_data, trend, min_vol_dist_data,
                            min_volume, min_distance, mode)
    except:
        pass

def trade_func(symbol):  # noqa
    with Live(generate_main_table(), refresh_per_second=2) as live:
        while True:
            try:
                tylerapi.grab_api_data()
                time.sleep(0.01)
                get_1m_data()
                time.sleep(0.01)
                get_5m_data()
                time.sleep(0.01)
                get_balance()
                time.sleep(0.01)
                get_orderbook()
                time.sleep(0.01)
                long_trade_condition()
                time.sleep(0.01)
                short_trade_condition()
                time.sleep(0.01)
                get_short_positions()
                time.sleep(0.01)
                get_long_positions()
                time.sleep(0.01)

            except Exception as e:
                log.warning(f"{e}")

            try:
                get_min_vol_dist_data(symbol)
                tylerapi.get_asset_volume_1m_1x(symbol, tylerapi.grab_api_data())
                time.sleep(30)
            except Exception as e:
                log.warning(f"{e}")

            live.update(generate_main_table())
            try:
                current_bid = get_orderbook()[0]
                current_ask = get_orderbook()[1]
            except Exception as e:
                log.warning(f"{e}")
            long_open_pos_qty = long_pos_qty
            short_open_pos_qty = short_pos_qty
            reduce_only = {"reduce_only": True}

            five_min_data = get_5m_data()
            market_data = get_market_data()

            if five_min_data is not None and market_data is not None:
                short_profit_price = round(
                    short_pos_price - (five_min_data[2] - five_min_data[3]),
                    int(market_data[0]),
                )
            else:
                pass

            if five_min_data is not None and market_data is not None:
                long_profit_price = round(
                    long_pos_price + (five_min_data[2] - five_min_data[3]),
                    int(market_data[0]),
                )
            else:
                pass
    
            # short_profit_price = round(
            #     short_pos_price - (get_5m_data()[2] - get_5m_data()[3]),
            #     int(get_market_data()[0]),
            # )

            # long_profit_price = round(
            #     long_pos_price + (get_5m_data()[2] - get_5m_data()[3]),
            #     int(get_market_data()[0]),
            # )


            if violent_mode:
                short_violent_trade_qty = (
                    short_open_pos_qty
                    * (get_1m_data()[3] - short_pos_price)
                    / (get_orderbook()[1] - get_1m_data()[3])
                )

                long_violent_trade_qty = (
                    long_open_pos_qty
                    * (get_1m_data()[3] - long_pos_price)
                    / (get_orderbook()[1] - get_1m_data()[3])
                )

            if config.avoid_fees:
                taker_fee_rate = config.linear_taker_fee
                current_price = get_current_price(exchange, symbol)
                long_order_value = current_price * long_open_pos_qty
                short_order_value = current_price * short_open_pos_qty
                min_price_increment_long = calculate_min_price_increment(long_pos_price, taker_fee_rate)
                min_price_increment_short = calculate_min_price_increment(short_pos_price, taker_fee_rate)

                # Calculate long_profit_prices
                price_difference = get_5m_data()[2] - get_5m_data()[3]
                price_scale = int(get_market_data()[0])
                long_profit_prices = calculate_long_profit_prices_avoidfees(
                    long_pos_price, price_difference, price_scale, min_price_increment_long, taker_fee_rate, long_order_value
                )

                # Calculate short_profit_prices
                short_profit_prices = calculate_short_profit_prices_avoidfees(
                    short_pos_price, price_difference, price_scale, min_price_increment_short, taker_fee_rate, short_order_value
                )
            else:
                if deleveraging_mode:
                    taker_fee_rate = config.linear_taker_fee
                    # Calculate long_profit_prices
                    price_difference = get_5m_data()[2] - get_5m_data()[3]
                    price_scale = int(get_market_data()[0])
                    long_profit_prices = calculate_long_profit_prices(long_pos_price, price_difference, price_scale)
                    short_profit_prices = calculate_short_profit_prices(short_pos_price, price_difference, price_scale)


            add_trade_qty = trade_qty

            # Longbias mode
            if longbias_mode:
                try:
                    if find_trend() == "long":
                        initial_long_entry(current_bid)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            and long_pos_qty < max_trade_qty
                            and add_short_trade_condition()
                        ):
                            try:
                                exchange.create_limit_buy_order(
                                    symbol, trade_qty, current_bid
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")
                except Exception as e:
                    log.warning(f"{e}")

            # Long entry logic if long enabled
            if (
                long_mode
                and long_trade_condition()
                and tyler_total_volume_5m > min_volume
                and find_5m_spread() > min_distance
                and long_pos_qty == 0
                and long_pos_qty < max_trade_qty
                and find_trend() == "long"
            ):
                try:
                    exchange.create_limit_buy_order(symbol, trade_qty, current_bid)
                    time.sleep(0.01)
                except Exception as e:
                    log.warning(f"{e}")
            else:
                pass

            # Add to long if long enabled
            if (
                long_pos_qty != 0
                and long_pos_qty < max_trade_qty
                and long_mode
                and find_1m_1x_volume() > min_volume
                and add_long_trade_condition()
                and find_trend() == "long"
                and current_bid < long_pos_price
            ):
                try:
                    cancel_entry()
                    time.sleep(0.05)
                except Exception as e:
                    log.warning(f"{e}")
                try:
                    exchange.create_limit_buy_order(symbol, add_trade_qty, current_bid)
                except Exception as e:
                    log.warning(f"{e}")

            # Short entry logic if short enabled
            if (
                short_mode
                and short_trade_condition()
                and tyler_total_volume_5m > min_volume
                and find_5m_spread() > min_distance
                and short_pos_qty == 0
                and short_pos_qty < max_trade_qty
                and find_trend() == "short"
            ):
                try:
                    exchange.create_limit_sell_order(symbol, trade_qty, current_ask)
                    time.sleep(0.01)
                except Exception as e:
                    log.warning(f"{e}")
            else:
                pass

            # Add to short if short enabled
            if (
                short_pos_qty != 0
                and short_pos_qty < max_trade_qty
                and short_mode
                and find_1m_1x_volume() > min_volume
                and add_short_trade_condition()
                and find_trend() == "short"
                and current_ask > short_pos_price
            ):
                try:
                    cancel_entry()
                    time.sleep(0.05)
                except Exception as e:
                    log.warning(f"{e}")
                try:
                    exchange.create_limit_sell_order(symbol, add_trade_qty, current_ask)
                except Exception as e:
                    log.warning(f"{e}")

            # LONG: Deleveraging Take profit logic
            if (
                deleveraging_mode == True
                or config.avoid_fees == True
                and long_pos_qty > 0
                and hedge_mode == True or
                violent_mode == True or
                long_mode == True or
                longbias_mode == True or
                aggressive_mode == True or
                btclinear_long_mode == True
            ):
                try:
                    get_open_orders()
                    time.sleep(0.05)
                except Exception as e:
                    log.warning(f"{e}")

                if long_profit_price != 0 or long_pos_price != 0:
                    try:
                        cancel_close()
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")

                    # Create separate limit sell orders for each take profit level
                    position_size = long_open_pos_qty / len(long_profit_prices)
                    for profit_price in long_profit_prices:
                        try:
                            exchange.create_limit_sell_order(
                                symbol, position_size, profit_price, reduce_only
                            )
                            time.sleep(0.05)
                        except Exception as e:
                            log.warning(f"{e}")
                            

            # LONG: Take profit logic
            if (
                deleveraging_mode == False
                or config.avoid_fees == False
                and long_pos_qty > 0
                and hedge_mode == True or
                long_mode == True or
                longbias_mode == True or
                aggressive_mode == True or
                btclinear_long_mode == True or
                violent_mode == True
            ):
                try:
                    get_open_orders()
                    time.sleep(0.05)
                except Exception as e:
                    log.warning(f"{e}")

                if long_profit_price != 0 or long_pos_price != 0:
                    try:
                        cancel_close()
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")
                    try:
                        exchange.create_limit_sell_order(
                            symbol, long_open_pos_qty, long_profit_price, reduce_only
                        )
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")

            # SHORT: Deleveraging Take profit logic
            if (
                deleveraging_mode == True
                or config.avoid_fees == True
                and short_pos_qty > 0
                and hedge_mode == True or
                violent_mode == True or
                short_mode == True or
                aggressive_mode == True or
                btclinear_short_mode == True
            ):
                try:
                    get_open_orders()
                    time.sleep(0.05)
                except Exception as e:
                    log.warning(f"{e}")

                if short_profit_price != 0 or short_pos_price != 0:
                    try:
                        cancel_close()
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")
                    # Create separate limit buy orders for each take profit level
                    position_size = short_open_pos_qty / len(short_profit_prices)
                    for profit_price in short_profit_prices:
                        try:
                            exchange.create_limit_buy_order(
                                symbol, position_size, profit_price, reduce_only
                            )
                            time.sleep(0.05)
                        except Exception as e:
                            log.warning(f"{e}")

            # SHORT: Take profit logic
            if (
                deleveraging_mode == False
                and config.avoid_fees == False
                and short_pos_qty > 0
                and hedge_mode == True or
                short_mode == True or
                aggressive_mode == True or
                btclinear_short_mode == True or
                violent_mode == True
            ):
                try:
                    get_open_orders()
                    time.sleep(0.05)
                except Exception as e:
                    log.warning(f"{e}")

                if short_profit_price != 0 or short_pos_price != 0:
                    try:
                        cancel_close()
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")
                    try:
                        exchange.create_limit_buy_order(
                            symbol, short_open_pos_qty, short_profit_price, reduce_only
                        )
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")

            # Linear BTC modes
            if btclinear_long_mode:
                try:
                    if find_trend() == "long":
                        initial_long_entry_linear_btc(current_bid)
                except Exception as e:
                    log.warning(f"{e}")

                    if (
                        get_orderbook()[1] < get_1m_data()[0]
                        or get_orderbook()[1] < get_5m_data()[0]
                    ):
                        try:
                            cancel_entry()
                            time.sleep(0.05)
                        except Exception as e:
                            log.warning(f"{e}")

            # Violent: Full mode
            if violent_mode:
                try:
                    if find_trend() == "short":
                        initial_short_entry(current_ask)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            # and short_pos_qty < max_trade_qty
                            and add_short_trade_condition()
                            and current_ask > short_pos_price
                        ):
                            trade_size = (
                                short_violent_trade_qty
                                if short_pos_qty < violent_max_trade_qty
                                else trade_qty
                            )
                            try:
                                exchange.create_limit_sell_order(
                                    symbol, trade_size, current_ask
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")

                    elif find_trend() == "long":
                        initial_long_entry(current_bid)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            # and long_pos_qty < max_trade_qty
                            and add_long_trade_condition()
                            and current_bid < long_pos_price
                        ):
                            trade_size = (
                                long_violent_trade_qty
                                if long_pos_qty < violent_max_trade_qty
                                else trade_qty
                            )
                            try:
                                exchange.create_limit_buy_order(
                                    symbol, trade_size, current_bid
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")

                    if (
                        get_orderbook()[1] < get_1m_data()[0]
                        or get_orderbook()[1] < get_5m_data()[0]
                    ):
                        try:
                            cancel_entry()
                            time.sleep(0.05)
                        except Exception as e:
                            log.warning(f"{e}")
                except Exception as e:
                    log.warning(f"{e}")


            # HEDGE: Full mode
            if hedge_mode:
                try:
                    if find_trend() == "short":
                        initial_short_entry(current_ask)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            and short_pos_qty < max_trade_qty
                            and add_short_trade_condition()
                            and current_ask > short_pos_price
                        ):
                            try:
                                exchange.create_limit_sell_order(
                                    symbol, trade_qty, current_ask
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")
                    elif find_trend() == "long":
                        initial_long_entry(current_bid)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            and long_pos_qty < max_trade_qty
                            and add_long_trade_condition()
                            and current_bid < long_pos_price
                        ):
                            try:
                                exchange.create_limit_buy_order(
                                    symbol, trade_qty, current_bid
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")
                    if (
                        get_orderbook()[1] < get_1m_data()[0]
                        or get_orderbook()[1] < get_5m_data()[0]
                    ):
                        try:
                            cancel_entry()
                            time.sleep(0.05)
                        except Exception as e:
                            log.warning(f"{e}")
                except Exception as e:
                    log.warning(f"{e}")

            # Aggressive HEDGE: Full mode
            if aggressive_mode:
                try:
                    if find_trend() == "short":
                        initial_short_entry(current_ask)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            and add_short_trade_condition()
                            and current_ask > short_pos_price
                        ):
                            try:
                                exchange.create_limit_sell_order(
                                    symbol, trade_qty, current_ask
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")
                    elif find_trend() == "long":
                        initial_long_entry(current_bid)
                        if (
                            find_1m_1x_volume() > min_volume
                            and find_5m_spread() > min_distance
                            and add_long_trade_condition()
                            and current_bid < long_pos_price
                        ):
                            try:
                                exchange.create_limit_buy_order(
                                    symbol, trade_qty, current_bid
                                )
                                time.sleep(0.01)
                            except Exception as e:
                                log.warning(f"{e}")
                    if (
                        get_orderbook()[1] < get_1m_data()[0]
                        or get_orderbook()[1] < get_5m_data()[0]
                    ):
                        try:
                            cancel_entry()
                            time.sleep(0.05)
                        except Exception as e:
                            log.warning(f"{e}")
                except Exception as e:
                    log.warning(f"{e}")

            orderbook_data = get_orderbook()
            data_1m = get_1m_data()
            data_5m = get_5m_data()

            if orderbook_data is not None and data_1m is not None and data_5m is not None:
                if orderbook_data[1] < data_1m[0] or orderbook_data[1] < data_5m[0]:
                    try:
                        cancel_entry()
                        time.sleep(0.05)
                    except Exception as e:
                        log.warning(f"{e}")
            else:
                log.warning("One or more functions returned None")
                
            # if (
            #     get_orderbook()[1] < get_1m_data()[0]
            #     or get_orderbook()[1] < get_5m_data()[0]
            # ):
            #     try:
            #         cancel_entry()
            #         time.sleep(0.05)
            #     except Exception as e:
            #         log.warning(f"{e}")


# Mode functions
def long_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "Long mode enabled for", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)
    # print(tylerapi.get_asset_total_volume_5m(symbol, tylerapi.api_data))


def short_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "Short mode enabled for", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)


def hedge_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "Hedge mode enabled for", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)


def aggressive_mode_func(symbol):
    print(
        Fore.LIGHTCYAN_EX + "Aggressive hedge mode enabled for",
        symbol + Style.RESET_ALL,
    )
    leverage_verification(symbol)
    trade_func(symbol)


def longbias_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "Longbias mode enabled for", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)

def linearbtclong_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "BTC Linear LONG mode enabled", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)

def linearbtcshort_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "BTC Linear SHORT mode enabled", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)

def violent_mode_func(symbol):
    print(Fore.LIGHTCYAN_EX + "Violent mode enabled use at your own risk use LOW lot size", symbol + Style.RESET_ALL)
    leverage_verification(symbol)
    trade_func(symbol)

    

# TO DO:

# Add a terminal like console / hotkeys for entries

# Argument declaration
if args.mode == "long":
    if args.symbol:
        long_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "short":
    if args.symbol:
        short_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "hedge":
    if args.symbol:
        hedge_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "aggressive":
    if args.symbol:
        aggressive_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "longbias":
    if args.symbol:
        longbias_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "btclinear-long":
    if args.symbol:
        linearbtclong_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "btclinear-short":
    if args.symbol:
        linearbtcshort_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")
elif args.mode == "violent":
    if args.symbol:
        violent_mode_func(args.symbol)
    else:
        symbol = input("Instrument undefined. \nInput instrument:")

        

if args.tg == "on":
    if args.tg:
        print(Fore.LIGHTCYAN_EX + "TG Enabled" + Style.RESET_ALL)
    else:
        print(Fore.LIGHTCYAN_EX + "TG Disabled" + Style.RESET_ALL)
