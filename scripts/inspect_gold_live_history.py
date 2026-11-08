"""Read the existing MT5 account's history; never log in or change any orders."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/gold_live_review/20261101'


def save(name,value):
    (RUN/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def table(name,rows):
    if not rows:
        (RUN/name).write_text('',encoding='utf-8');return
    with (RUN/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def collect(path):
    RUN.mkdir(parents=True,exist_ok=True)
    start=datetime(2021,1,1,tzinfo=timezone.utc);end=datetime.now(timezone.utc)+timedelta(days=2)
    meta=dict(collected_utc=datetime.now(timezone.utc).isoformat(),terminal_executable=str(path),
        period_start=start.isoformat(),period_end=end.isoformat(),
        note='End has a two-day allowance for broker-clock offsets; returned deals are already executed history.',
        order_or_account_mutations=False)
    try:
        ok=mt5.initialize(str(path),timeout=10000)
        meta['ipc_connected']=bool(ok)
        if not ok:
            meta['error']=list(mt5.last_error());save('COLLECTION.json',meta)
            print(json.dumps(meta,ensure_ascii=True),flush=True);return
        term=mt5.terminal_info();account=mt5.account_info()
        if term is None or account is None:
            meta['error']=list(mt5.last_error());save('COLLECTION.json',meta)
            print(json.dumps(meta,ensure_ascii=True),flush=True);return
        meta.update(terminal_connected=term.connected,data_path=term.data_path,
            account_fingerprint=hashlib.sha256(f'{account.server}:{account.login}'.encode()).hexdigest()[:16],
            account={k:getattr(account,k) for k in ['server','company','currency','trade_mode','margin_mode']})
        deals=mt5.history_deals_get(start,end)
        meta['deals_error']=list(mt5.last_error()) if deals is None else None
        orders=mt5.history_orders_get(start,end)
        meta['orders_error']=list(mt5.last_error()) if orders is None else None
        positions=mt5.positions_get()
        meta['positions_error']=list(mt5.last_error()) if positions is None else None
        dr=[x._asdict() for x in deals] if deals is not None else []
        od=[x._asdict() for x in orders] if orders is not None else []
        po=[x._asdict() for x in positions] if positions is not None else []
        save('deals.json',dr);save('orders.json',od);save('open_positions.json',po)
        table('deals.csv',dr);table('orders.csv',od)
        gold_symbols=sorted({x['symbol'] for x in dr+po if 'XAU' in x['symbol'].upper() or 'GOLD' in x['symbol'].upper()})
        specs={}
        for symbol in gold_symbols:
            info=mt5.symbol_info(symbol)
            if info is not None:
                specs[symbol]={k:getattr(info,k) for k in ['currency_profit','trade_contract_size','trade_tick_size','trade_tick_value','digits','point']}
        save('GOLD_SYMBOL_SPECS.json',specs)
        meta.update(deal_count=len(dr),order_count=len(od),open_position_count=len(po),
            traded_symbols=dict(Counter(x['symbol'] for x in dr if x['type'] in [0,1])),
            gold_deal_count=sum(x['symbol'] in gold_symbols and x['type'] in [0,1] for x in dr))
        save('COLLECTION.json',meta)
        print(json.dumps(meta,ensure_ascii=True),flush=True)
    finally:
        mt5.shutdown()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--terminal',type=Path,required=True)
    collect(parser.parse_args().terminal)
