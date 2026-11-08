"""Collect silver history from the existing MT5 connection; no trading/account calls."""
import json

import MetaTrader5 as mt5
import numpy as np

from collect_scalp_intermarket_v9 import stamp,validate
from prepare_can_ho_tro_scalp import sha,write_json
from research_scalp_metals_v14 import RUN,freeze_protocol,w


def main():
    freeze_protocol();chunks=RUN/'silver_chunks';chunks.mkdir(exist_ok=True)
    assert mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe',timeout=10000),mt5.last_error()
    meta=dict(source='existingconnectedMT5copy_rates_rangeM5',protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),
        no_account_login_or_order_calls=True,requests=[])
    selected=False;original_visible=None
    try:
        assert mt5.terminal_info().connected
        info=mt5.symbol_info('XAGUSD');assert info and info.path.startswith('Metals\\')
        original_visible=info.visible
        if not original_visible:
            assert mt5.symbol_select('XAGUSD',True),mt5.last_error();selected=True
        meta['symbol']=dict(name='XAGUSD',description=info.description,path=info.path,original_visible=original_visible)
        parts=[]
        for year in range(2021,2027):
            start=stamp(year);stop=min(stamp(year+1),stamp(2026,10,25));path=chunks/(str(year)+'.npz')
            if path.exists():a=np.load(path)['rates']
            else:
                a=mt5.copy_rates_range('XAGUSD',mt5.TIMEFRAME_M5,start,stop-1)
                assert a is not None and len(a),('XAGUSD',year,mt5.last_error())
                validate(a);np.savez_compressed(path,rates=a)
            validate(a);assert np.all((a['time']>=start)&(a['time']<stop));parts.append(a)
            meta['requests'].append(dict(year=year,rows=len(a),first=int(a['time'][0]),last=int(a['time'][-1]),sha256=sha(path)))
            print('SILVER',year,len(a),flush=True)
        rates=np.concatenate(parts);validate(rates)
        assert rates['time'][0]<=stamp(2021,1,5),'Insufficient initial training history'
        gold=np.load(w.BASE/'rates.npz')['m5'];checks=[]
        for year,month,day in ((2021,10,26),(2024,5,6),(2026,10,20)):
            start=stamp(year,month,day);a=mt5.copy_rates_range('XAUUSD',mt5.TIMEFRAME_M5,start,start+86400-1)
            expected=gold[(gold['time']>=start)&(gold['time']<start+86400)]
            exact=a is not None and len(a)==len(expected) and all(np.array_equal(a[k],expected[k]) for k in ('time','open','high','low','close'))
            checks.append(dict(start=start,rows_current=len(a) if a is not None else 0,rows_frozen=len(expected),exact_ohlc_time=bool(exact)))
        assert all(r['exact_ohlc_time'] for r in checks),'Gold feed mismatch'
        meta['gold_feed_compatibility']=checks
        meta['rows']=len(rates);meta['first']=int(rates['time'][0]);meta['last']=int(rates['time'][-1])
    finally:
        if selected:
            assert mt5.symbol_select('XAGUSD',False),'Could not restore original silver MarketWatch visibility'
        meta['original_marketwatch_visibility_restored']=original_visible is not None and mt5.symbol_info('XAGUSD').visible==original_visible
        mt5.shutdown()
    path=RUN/'silver_rates.npz'
    if path.exists():np.testing.assert_array_equal(np.load(path)['rates'],rates)
    else:np.savez_compressed(path,rates=rates)
    meta['data_sha256']=sha(path);write_json(RUN/'SILVER_DATA_MANIFEST.json',meta)
    print('SILVERDATA',len(rates),meta['data_sha256'],flush=True)


if __name__=='__main__':main()
