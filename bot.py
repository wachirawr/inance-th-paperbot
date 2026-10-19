#!/usr/bin/env python3
"""Binance TH public-data scanner + PAPER-ONLY simulator. No trading API code."""
from __future__ import annotations
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / 'paperbot.db'
API_BASE = 'https://api.binance.th'
LOG = logging.getLogger('paperbot')


def load_env(path: Path = HERE / '.env') -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('#') or '=' not in raw:
            continue
        key, value = raw.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        os.environ[key] = value


def conf():
    symbols = [s.strip().upper() for s in os.getenv('SYMBOLS', 'BTCTHB,ETHTHB,SOLTHB').split(',') if s.strip()]
    selected = os.getenv('TRADE_SYMBOL', 'BTCTHB').upper().strip()
    if selected not in symbols:
        raise ValueError('TRADE_SYMBOL must be included in SYMBOLS')
    if os.getenv('MODE', 'PAPER').strip().upper() != 'PAPER':
        raise ValueError('Safety lock: only MODE=PAPER is supported')
    result = {
        'symbols': symbols,
        'trade_symbol': selected,
        'poll_seconds': max(60, int(os.getenv('POLL_SECONDS', '60'))),
        'initial_cash': float(os.getenv('START_BALANCE_THB', '100000')),
        'order_thb': float(os.getenv('ORDER_THB', '2000')),
        'fee_rate': float(os.getenv('FEE_RATE', '0.0025')),
        'slip_rate': float(os.getenv('SLIPPAGE_RATE', '0.0005')),
        'stop_loss': float(os.getenv('STOP_LOSS_PCT', '2'))/100,
        'take_profit': float(os.getenv('TAKE_PROFIT_PCT', '4'))/100,
        'interval': os.getenv('CANDLE_INTERVAL', '15m'),
        'telegram_token': os.getenv('TELEGRAM_BOT_TOKEN', '').strip(),
        'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID', '').strip(),
    }
    assert result['initial_cash'] > 0 and result['order_thb'] > 0
    assert 0 <= result['fee_rate'] < 0.1 and 0 <= result['slip_rate'] < 0.1
    assert 0 < result['stop_loss'] < 1 and 0 < result['take_profit'] < 1
    return result


def get_json(url, timeout=12):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'PaperBotReadOnly/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    # Some Binance TH responses may be wrapped in {code, data}.
    if isinstance(payload, dict) and 'data' in payload and 'code' in payload:
        if str(payload.get('code')) not in ('0', '200'):
            raise ValueError('API error: ' + str(payload.get('msg', payload['code'])))
        return payload['data']
    return payload


def public_api(path: str, params: dict):
    query = urllib.parse.urlencode(params)
    return get_json(API_BASE + path + '?' + query)


def parse_book(result):
    if isinstance(result, list):
        if len(result) != 1:
            raise ValueError('unexpected ticker list')
        result = result[0]
    bid, ask = float(result['bidPrice']), float(result['askPrice'])
    if bid <= 0 or ask <= 0 or bid > ask:
        raise ValueError('Invalid bid/ask')
    return bid, ask


def fetch_book(symbol):
    result = public_api('/api/v1/ticker/bookTicker', {'symbol': symbol})
    return parse_book(result)


def closed_candles(rows, now_ms):
    candles = []
    for row in rows:
        if len(row) < 7:
            continue
        close_ts = int(row[6])
        close = float(row[4])
        if 0 < close and close_ts <= now_ms - 2000:
            candles.append((close_ts, close))
    candles.sort()
    return candles


def fetch_candles(symbol, interval):
    rows = public_api('/api/v1/klines', {'symbol': symbol, 'interval': interval, 'limit': 60})
    if not isinstance(rows, list):
        raise ValueError('Unexpected klines response')
    return closed_candles(rows, int(time.time()*1000))


def crossover(closes, short=9, long=21):
    """Signal from LAST TWO fully CLOSED candles only."""
    if len(closes) < long + 1:
        return 'NOT_ENOUGH_DATA'
    before_short = sum(closes[-short-1:-1])/short
    before_long = sum(closes[-long-1:-1])/long
    after_short = sum(closes[-short:])/short
    after_long = sum(closes[-long:])/long
    if before_short <= before_long and after_short > after_long:
        return 'BUY'
    if before_short >= before_long and after_short < after_long:
        return 'SELL'
    return 'HOLD'


def connect(cfg):
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS samples (ts INTEGER, symbol TEXT, bid REAL, ask REAL, spread_pct REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, ts INTEGER, symbol TEXT, side TEXT, qty REAL, price REAL, fee REAL, cash_after REAL, realized_pnl REAL, reason TEXT)')
    if conn.execute("SELECT value FROM meta WHERE key='cash'").fetchone() is None:
        set_value(conn, 'cash', cfg['initial_cash'])
        set_value(conn, 'qty', 0)
        set_value(conn, 'entry_total', 0)
        set_value(conn, 'entry_price', 0)
        set_value(conn, 'last_closed_candle', 0)
        set_value(conn, 'last_success_ts', 0)
        set_value(conn, 'last_summary_ts', 0)
        conn.commit()
    return conn


def value(conn, name, default='0'):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (name,)).fetchone()
    return row[0] if row else default


def set_value(conn, name, val):
    conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (name, str(val)))


def message(cfg, text):
    token, chat_id = cfg['telegram_token'], cfg['telegram_chat_id']
    if not token or not chat_id:
        return
    encoded = urllib.parse.urlencode({'chat_id': chat_id, 'text': text}).encode()
    req = urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage', data=encoded, method='POST')
    try:
        # Do not log a URL containing the secret bot token.
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
        if status != 200:
            LOG.warning('Telegram returned status %s', status)
    except Exception as ex:
        LOG.warning('Telegram message failed: %s', type(ex).__name__)


def trade(conn, cfg, side, bid, ask, reason):
    """Pure accounting: local SQLite only; never sends an exchange order."""
    cash = float(value(conn, 'cash'))
    qty = float(value(conn, 'qty'))
    rate, slip = cfg['fee_rate'], cfg['slip_rate']
    if side == 'BUY':
        if qty > 0:
            return None
        budget = min(cfg['order_thb'], cash/(1+rate))
        if budget < 100:
            return None
        price = ask*(1+slip)
        newqty = budget/price
        fee = budget*rate
        cash_after = cash - budget - fee
        if cash_after < -0.000001:
            raise RuntimeError('Safety check: negative cash')
        set_value(conn, 'cash', cash_after)
        set_value(conn, 'qty', newqty)
        set_value(conn, 'entry_total', budget + fee)
        set_value(conn, 'entry_price', price)
        pnl = 0
        LOG.info('SIMULATED BUY %s qty=%.8f price=%.2f', cfg['trade_symbol'], newqty, price)
    else:
        if qty <= 0:
            return None
        price = bid*(1-slip)
        gross = qty*price
        fee = gross*rate
        cash_after = cash + gross-fee
        pnl = (gross-fee)-float(value(conn, 'entry_total'))
        set_value(conn, 'cash', cash_after)
        set_value(conn, 'qty', 0)
        set_value(conn, 'entry_total', 0)
        set_value(conn, 'entry_price', 0)
        newqty = qty
        LOG.info('SIMULATED SELL %s qty=%.8f price=%.2f pnl=%.2f', cfg['trade_symbol'], qty, price, pnl)
    conn.execute('INSERT INTO trades(ts,symbol,side,qty,price,fee,cash_after,realized_pnl,reason) VALUES (?,?,?,?,?,?,?,?,?)',
                 (int(time.time()), cfg['trade_symbol'], side, newqty, price, fee, cash_after, pnl, reason))
    conn.commit()
    label = 'BUY' if side == 'BUY' else 'SELL'
    return f'PAPER {label} | {cfg["trade_symbol"]}\nPrice: {price:,.2f} THB\nQty: {newqty:.8f}\nFee: {fee:,.2f} THB\nRealized PnL: {pnl:+,.2f} THB\nReason: {reason}\n(No real trades)'


def equity(conn, cfg, bid):
    cash = float(value(conn, 'cash'))
    qty = float(value(conn, 'qty'))
    net_liquidation = qty*bid*(1-cfg['slip_rate'])*(1-cfg['fee_rate'])
    return cash+net_liquidation


def run_cycle(conn, cfg, send=True):
    books = {}
    now = int(time.time())
    for symbol in cfg['symbols']:
        bid, ask = fetch_book(symbol)
        spread = (ask-bid)/((ask+bid)/2)*100
        conn.execute('INSERT INTO samples(ts,symbol,bid,ask,spread_pct) VALUES (?,?,?,?,?)', (now, symbol, bid, ask, spread))
        books[symbol] = (bid, ask)
        LOG.info('SCAN %s bid=%.2f ask=%.2f spread=%.3f%%', symbol, bid, ask, spread)
    conn.commit()
    bid, ask = books[cfg['trade_symbol']]
    qty = float(value(conn, 'qty'))
    if qty > 0:
        entry = float(value(conn, 'entry_price'))
        est_price = bid * (1-cfg['slip_rate'])
        # Stop/take-profit measured from estimated executable selling price.
        if est_price <= entry*(1-cfg['stop_loss']):
            msg = trade(conn, cfg, 'SELL', bid, ask, 'STOP_LOSS')
            if msg and send: message(cfg, msg)
        elif est_price >= entry*(1+cfg['take_profit']):
            msg = trade(conn, cfg, 'SELL', bid, ask, 'TAKE_PROFIT')
            if msg and send: message(cfg, msg)
    candles = fetch_candles(cfg['trade_symbol'], cfg['interval'])
    if len(candles) < 22:
        raise ValueError('Not enough closed 15m candles (needs 22)')
    last_ts = candles[-1][0]
    seen_ts = int(value(conn, 'last_closed_candle'))
    if last_ts > seen_ts:
        set_value(conn, 'last_closed_candle', last_ts)
        conn.commit()
        if seen_ts > 0:  # never buy from stale signals at startup
            signal = crossover([c[1] for c in candles])
            if signal == 'BUY' and float(value(conn, 'qty')) <= 0:
                msg = trade(conn, cfg, 'BUY', bid, ask, 'SMA_9_21_UP_CROSS')
                if msg and send: message(cfg, msg)
            elif signal == 'SELL' and float(value(conn, 'qty')) > 0:
                msg = trade(conn, cfg, 'SELL', bid, ask, 'SMA_9_21_DOWN_CROSS')
                if msg and send: message(cfg, msg)
            LOG.info('closed candle signal=%s', signal)
        else:
            LOG.info('first startup: warm-up candle recorded, no trade')
    set_value(conn, 'last_success_ts', now)
    if now-int(value(conn, 'last_summary_ts')) >= 6*3600:
        net = equity(conn, cfg, bid)
        summary = ('PAPER BOT: RUNNING\n' + ' | '.join(cfg['symbols']) +
                   f'\nVirtual equity: {net:,.2f} THB\nVirtual cash: {float(value(conn,"cash")):,.2f} THB' +
                   f'\nVirtual PnL: {net-cfg["initial_cash"]:+,.2f} THB\nNo real money used.')
        LOG.info(summary.replace('\n', ' | '))
        if send: message(cfg, summary)
        set_value(conn, 'last_summary_ts', now)
    # Retain the last 30 days of snapshots; no loss of trades.
    if now % 86400 < cfg['poll_seconds']:
        conn.execute('DELETE FROM samples WHERE ts < ?', (now-30*86400,))
    conn.commit()


def status(conn, cfg):
    balances = (float(value(conn,'cash')), float(value(conn,'qty')))
    row = conn.execute('SELECT bid, ts FROM samples WHERE symbol=? ORDER BY ts DESC LIMIT 1', (cfg['trade_symbol'],)).fetchone()
    net = equity(conn, cfg, row[0]) if row else balances[0]
    print('MODE: PAPER ONLY / NO REAL ORDER API')
    print('Scans:', ', '.join(cfg['symbols']))
    print('Virtual cash: {:,.2f} THB'.format(balances[0]))
    print('Simulated BTC qty (or configured asset): {:.8f}'.format(balances[1]))
    print('Estimated virtual equity: {:,.2f} THB'.format(net))
    print('Virtual P&L since start: {:+,.2f} THB'.format(net-cfg['initial_cash']))
    print('Last complete scan UTC:', datetime.fromtimestamp(int(value(conn,'last_success_ts')), timezone.utc).isoformat() if value(conn,'last_success_ts') != '0' else 'NONE')
    print('Simulated trades:', conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0])
    for ts, side, price, qty, pnl in conn.execute('SELECT ts,side,price,qty,realized_pnl FROM trades ORDER BY id DESC LIMIT 5'):
        print(' ', datetime.fromtimestamp(ts, timezone.utc).isoformat(), side, '{:,.2f}'.format(price), '{:.8f}'.format(qty), '{:+.2f}'.format(pnl))


def chatid(cfg):
    token = cfg['telegram_token']
    if not token:
        print('Set TELEGRAM_BOT_TOKEN in .env first (do not share it).')
        return 1
    result = get_json('https://api.telegram.org/bot'+token+'/getUpdates')
    if not result.get('ok'):
        print('Telegram did not accept the request')
        return 1
    for update in reversed(result.get('result', [])):
        item = update.get('message') or update.get('channel_post')
        if item and item.get('chat',{}).get('id'):
            print('TELEGRAM_CHAT_ID=' + str(item['chat']['id']))
            return 0
    print('No chat found. Open your new bot in Telegram, press Start, send Hello and retry.')
    return 1


def doctor(cfg):
    print('Checking public read-only Binance TH endpoints...')
    for symbol in cfg['symbols']:
        bid, ask = fetch_book(symbol)
        print(symbol, 'bid', bid, 'ask', ask)
    candles = fetch_candles(cfg['trade_symbol'], cfg['interval'])
    print(cfg['trade_symbol'], 'fully closed candles:', len(candles))
    if len(candles) < 22:
        raise ValueError('Need at least 22 closed candles')
    print('OK: no Binance API key or account used. Mode=PAPER.')


def main():
    load_env()
    cfg = conf()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    command = sys.argv[1] if len(sys.argv)>1 else 'help'
    if command == 'chatid':
        return chatid(cfg)
    if command == 'doctor':
        doctor(cfg)
        return 0
    if command not in ('run','once','status','help'):
        print('Usage: python3 bot.py doctor | chatid | once | run | status')
        return 2
    if command == 'help':
        print('Usage: python3 bot.py doctor | chatid | once | run | status')
        return 0
    conn = connect(cfg)
    if command == 'status':
        status(conn,cfg)
        return 0
    if command == 'once':
        run_cycle(conn,cfg)
        status(conn,cfg)
        return 0
    message(cfg,'PAPER BOT STARTED - monitoring '+','.join(cfg['symbols'])+'. No live trading permissions.')
    err_count = 0
    while True:
        started = time.time()
        try:
            run_cycle(conn,cfg)
            err_count = 0
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            err_count += 1
            LOG.error('SCAN ERROR (#%d) %s: %s', err_count,type(ex).__name__,str(ex)[:220])
            if err_count in (1,3,10) or (err_count > 10 and err_count % 60 == 0):
                message(cfg, f'PAPER BOT ERROR #{err_count}: {type(ex).__name__} - Check server logs. No trading attempted.')
        time.sleep(max(1, cfg['poll_seconds']-(time.time()-started)))

if __name__=='__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Stopped')
    except Exception as ex:
        LOG.exception('Fatal error: %s', ex)
        sys.exit(1)
