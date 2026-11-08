"""Recover chart-visible historical fills and compare them with the tested rules.

Only whitelisted chart inputs and trade objects are saved. Chart profiles may
contain Telegram credentials; never copy the entire profile into an artifact.
"""
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from inspect_gold_live_history import ROOT, RUN, save, table

BASE=Path(r'C:\Users\ductr\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075')
INPUTS={'BaseMaxBars','BaseBarATR','BaseTotalATR','DepartATR','DepartBars','LegInBars','AtrLen',
        'MaxHistory','MaxTests','MaxAgeBars','UseFlip','FlipLifeBars','MaxZones','MinScoreShow',
        'HtfPeriod','LtfPeriod','UseLtfConfirm','FilterKillzones','LtfBarsScan','InpSlMode',
        'SlBufferATR','MaxSlPips','MinSlPips','InpEntryMode','InpTpMode','InpTp1RR','InpTp2RR',
        'InpTp1Pips','InpTp2Pips','MinRR','InpUseAutoBE','InpBeTriggerPips','InpBeTriggerATR','InpBeOffsetPips'}
FILL=re.compile(r'autotrade #(\d+) (buy|sell) ([\d.]+) (\S+) at ([\d.]+)')
PAIR=re.compile(r'autotrade #(\d+) -> #(\d+), (?:(SL|TP), )?profit (-?\d+\.\d{2})(?:,|$)')
DEAL=re.compile(r'deal #(\d+) (buy|sell) ([\d.]+) (\S+) at ([\d.]+) done \(based on order #(\d+)\)')
MODIFY=re.compile(r'modify #(\d+) (buy|sell) ([\d.]+) (\S+) -> sl: ([\d.]+), tp: ([\d.]+) done in')


def text(path):
    raw=path.read_bytes()
    return raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig',errors='replace')


def props(block):
    return dict(line.split('=',1) for line in block.splitlines() if '=' in line)


def iso(t):
    # This formats the recorded epoch; it does not establish broker-clock UTC.
    return datetime.fromtimestamp(int(t),tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def journal():
    fills={};mods=[];closed_requests=[];manifest=[]
    for p in sorted((BASE/'logs').glob('20??????.log')):
        contents=text(p); relevant=False
        for number,line in enumerate(contents.splitlines(),1):
            cols=line.split('\t',4)
            if len(cols)!=5 or cols[3]!='Trades':continue
            stamp=p.stem[:4]+'-'+p.stem[4:6]+'-'+p.stem[6:8]+' '+cols[2]
            try:clock=datetime.fromisoformat(stamp)
            except ValueError:continue
            msg=cols[4];fill=DEAL.search(msg)
            if fill:
                ticket,side,volume,symbol,price,order=fill.groups()
                if symbol!='XAUUSD':continue
                value=dict(ticket=int(ticket),side=side,volume=float(volume),symbol=symbol,price=float(price),
                    order=int(order),journal_clock=clock.isoformat(),source=p.name,line=number)
                if int(ticket) in fills:
                    before=fills[int(ticket)]
                    assert (before['side'],before['volume'],before['price'],before['order'])==(value['side'],value['volume'],value['price'],value['order'])
                fills[int(ticket)]=value;relevant=True
            modified=MODIFY.search(msg)
            if modified:
                order,side,volume,symbol,sl,tp=modified.groups()
                if symbol!='XAUUSD':continue
                mods.append(dict(order=int(order),side=side,volume=float(volume),sl=float(sl),tp=float(tp),
                    journal_clock=clock.isoformat(),source=p.name,line=number));relevant=True
            close=re.search(r'market (buy|sell) ([\d.]+) XAUUSD, close #(\d+) (buy|sell) ([\d.]+) XAUUSD ([\d.]+)',msg)
            if close and not any(word in msg for word in ['failed','accepted']):
                closed_requests.append(dict(position_order=int(close[3]),journal_clock=clock.isoformat(),source=p.name,line=number))
        if relevant:
            manifest.append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    return fills,mods,closed_requests,manifest


def recover():
    arrows={};connectors={};profiles=[];errors=[]
    for p in sorted((BASE/'MQL5/Profiles/Charts').rglob('*.chr')):
        contents=text(p)
        if 'duc_tri_can_ho_tro' not in contents:continue
        data=props(contents.split('<window>')[0])
        inputs={key:value for key,value in props(contents).items() if key in INPUTS}
        paths=re.findall(r'^path=(.*duc_tri_can_ho_tro.*)$',contents,re.M)
        profiles.append(dict(path=str(p),modified_epoch=p.stat().st_mtime,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            symbol=data.get('symbol'),period_size=data.get('period_size'),indicator_paths=paths,inputs=inputs,
            state_scope='Saved profile, not proof these inputs were used at every historical entry.'))
        for block in re.findall(r'<object>\s*(.*?)\s*</object>',contents,re.S):
            values=props(block);name=values.get('name','');fill=FILL.match(name);pair=PAIR.match(name)
            if fill:
                ticket,side,volume,symbol,price=fill.groups()
                if symbol!='XAUUSD':continue
                row=dict(ticket=int(ticket),side=side,volume=float(volume),symbol=symbol,price=float(price),
                    recorded_time=int(values['date1']),description=values.get('descr',''),source=str(p))
                if int(ticket) in arrows:
                    before=arrows[int(ticket)]
                    assert (before['side'],before['volume'],before['price'],before['recorded_time'])==(row['side'],row['volume'],row['price'],row['recorded_time'])
                arrows[int(ticket)]=row
            elif pair:
                entry,exit,reason,profit=pair.groups()
                key=(int(entry),int(exit))
                row=dict(entry_ticket=int(entry),exit_ticket=int(exit),reason=reason or 'UNSPECIFIED',gross_profit=float(profit),
                    recorded_entry_time=int(values['date1']),recorded_exit_time=int(values['date2']),
                    entry_price=float(values['value1']),exit_price=float(values['value2']),source=str(p))
                if key in connectors:
                    assert connectors[key]['gross_profit']==row['gross_profit']
                connectors[key]=row
            elif name.startswith('autotrade ') and ' -> ' in name:
                errors.append(dict(source=str(p),unparsed_connector=name))
    save('SAVED_PROFILE_INPUTS.json',profiles)
    save('TRADE_ARROW_OBJECTS.json',list(arrows.values()))
    save('TRADE_CONNECTORS.json',list(connectors.values()))
    save('UNPARSED_TRADE_OBJECTS.json',errors)
    return profiles,arrows,connectors,errors


def stat(rows):
    values=[x['gross_profit'] for x in rows];loss=-sum(min(0,x) for x in values)
    return dict(n=len(rows),positive=sum(x>0 for x in values),negative=sum(x<0 for x in values),
        zero=sum(x==0 for x in values),gross_profit=sum(values),gross_wins=sum(max(0,x) for x in values),
        gross_losses=loss,gross_PF=sum(max(0,x) for x in values)/loss if loss else None,
        positive_pct=100*sum(x>0 for x in values)/len(rows) if rows else None)


def fixtures():
    assert FILL.match('autotrade #1 buy 0.2 XAUUSD at 100.00, XAUUSD').groups()==('1','buy','0.2','XAUUSD','100.00')
    assert PAIR.match('autotrade #1 -> #2, SL, profit 2.00, XAUUSD').groups()==('1','2','SL','2.00')
    assert PAIR.match('autotrade #1 -> #2, profit -20.0') is None
    assert not DEAL.search('failed market buy 0.2 XAUUSD [Market closed]')
    assert math.isclose(stat([dict(gross_profit=2.),dict(gross_profit=-1.)])['gross_PF'],2.)


def report(rows,summary,profiles):
    s=summary['stats'];p=profiles[0]['inputs'] if profiles else {}
    # Source-level feasibility check of the saved preset, without optimizing it.
    source=(ROOT/'duc_tri_can_ho_tro.mq5').read_text(encoding='utf-8-sig')
    assert 'rr1 < MinRR || rr2 < rr1)' in source
    assert '(isBuySignal && tp1 >= tp2)' in source
    conflict=(p.get('InpTpMode')=='0' and float(p.get('MinRR','0'))>=float(p.get('InpTp2RR','2')))
    save('SAVED_PRESET_CHECK.json',dict(hybrid_mode=p.get('InpTpMode')=='0',min_rr=p.get('MinRR'),
        tp2_rr=p.get('InpTp2RR'),nominal_plan_constraints_conflict=conflict,
        explanation='The v3.01 plan requires TP1 strictly below TP2 in reward distance and RR1>=MinRR. With MinRR=2 and TP2=2R these nominal inequalities conflict.',
        historical_inputs_not_established=True))
    differences=[('InpTpMode','TP_MODE_RR (1)','Hybrid (0)'),('InpEntryMode','Market confirm (1)','Dual recommend (0)'),
        ('FilterKillzones','true',p.get('FilterKillzones')),('SlBufferATR','0.3',p.get('SlBufferATR')),
        ('MaxSlPips','100',p.get('MaxSlPips')),('MinRR','1.5',p.get('MinRR'))]
    # Count overlapping completed positions, with exits preceding entries at the same time.
    timeline=[]
    for r in rows:
        timeline.extend([(r['entry_epoch'],1),(r['exit_epoch'],-1)])
    concurrent=peak=0
    for _,delta in sorted(timeline):
        concurrent+=delta;peak=max(peak,concurrent)
    lines=['# Đối chiếu các lệnh đã giao dịch với indicator Cản Hỗ Trợ','',
        '**Có bằng chứng về một mẫu lệnh đã đóng có lãi trong dữ liệu chart MT5 lưu trên máy. Cách sử dụng thể hiện trong dữ liệu khác cấu hình Pure R:R đã backtest. Kết luận âm của backtest trước cần giới hạn ở đúng bộ quy tắc đã mô phỏng.**','',
        '## 1. Đã lấy được những gì?','',
        'Đọc tài khoản MT5 đang mở bằng API chỉ đọc: MetaQuotes-Demo, hiện trả về một giao dịch nạp tiền demo, 0 lệnh XAUUSD và 0 vị thế. Đây là tài khoản khác dữ liệu lịch sử trong profile cũ. Không đổi tài khoản, không đặt/đóng/sửa lệnh.',
        '', f"Trong profile cũ Market Overview/chart01.chr, khôi phục được **{s['n']} cặp giao dịch XAUUSD đã đóng**, đóng từ 28/09 đến 22/10/2026. Có **{summary['fills_crosschecked']} lượt khớp** đối chiếu được với journal; cả {s['n']} cặp đều khớp số lời/lỗ hiển thị với phép tính từ giá entry/exit và khối lượng, tương ứng 100 oz/lot. Các cặp đều có volume đóng bằng volume vào.",
        '', '**Đây là các lệnh được vẽ trên chart lưu, chưa phải statement toàn bộ tài khoản.** Không giải mã file cache proprietary và không lấy tổng số dư/lãi lỗ của tài khoản cũ từ tài khoản mới.',
        '', '## 2. Hiệu suất mẫu khôi phục','',
        '| Chỉ tiêu | Kết quả |','|---|---:|',
        f"| Số lệnh đóng | {s['n']} |",f"| Lệnh có P&L gộp dương / âm | {s['positive']} / {s['negative']} |",
        f"| Tỷ lệ P&L gộp dương | {s['positive_pct']:.2f}% |",
        f"| Tổng P&L gộp theo giá khớp | **{s['gross_profit']:+.2f} USD** |",
        f"| Tổng lãi gộp / tổng lỗ gộp | {s['gross_wins']:.2f} / {s['gross_losses']:.2f} USD |",
        f"| Profit Factor gộp | **{s['gross_PF']:.3f}** |",'',
        'P&L gộp ở đây đã phản ánh giá khớp entry/exit nên không trừ spread thêm lần nữa. Chưa có commission/swap/fee của tài khoản cũ để xác nhận P&L ròng. Tỷ lệ dương bao gồm cả một lệnh +0,60 USD; không gán nhãn mọi lần chạm SL là lệnh thua.',
        '', '| Ngày đóng (clock lưu trên chart) | Lệnh đóng | Lãi / lỗ | P&L gộp USD |',
        '|---|---:|---:|---:|']
    for day,a in summary['days'].items():
        lines.append(f"| {day} | {a['n']} | {a['positive']} / {a['negative']} | {a['gross_profit']:+.2f} |")
    lines+=['', 'Ngày 20/10 có một cụm kết quả dương rõ rệt. Lệnh lời lớn nhất trong mẫu là SELL 0,20 lot, 4145,65 → 4119,58, +521,40 USD gộp. Đây là đặc điểm của mẫu nhỏ, chưa chứng minh mức kỳ vọng dài hạn hay tính ổn định.',
        '', '## 3. Cách giao dịch quan sát được khác backtest','',
        f"- Có tới **{peak} vị thế đã đóng trong mẫu cùng tồn tại** tại một thời điểm. Backtest vừa rồi chặn một vị thế; đây là khác biệt về mức tiếp xúc và cách nhận thêm lệnh.",
        f"- **{summary['trades_with_modifications']}/{s['n']} lệnh** có bản ghi sửa SL/TP hoàn tất trong journal.",
        '- Có lệnh thay đổi TP nhiều lần; có lệnh đóng bởi SL nhưng vẫn lời nhờ stop đã được dời. Journal không tự chứng minh mọi lần sửa do thao tác tay hay do EA khác.',
        '- Thời gian vào lệnh không luôn đúng open M5 kế tiếp. Không đủ dữ liệu để khôi phục tiêu chí chọn/bỏ tín hiệu của bạn.',
        '', '| Input | Bộ đã backtest | Profile chart lưu |','|---|---|---|']
    for name,before,after in differences:
        lines.append(f'| {name} | {before} | {after} |')
    lines+=['', 'Profile được lưu ngày 31/10/2026. Nó chứng minh cấu hình đã lưu khác bộ đã test; **không chứng minh tất cả lệnh trước đó dùng nguyên cấu hình này**. Các lệnh trước khi biên dịch v3.01 ngày 23/10 cũng chưa xác định được chính xác hash phiên bản nguồn tại lúc vào lệnh.',
        '', '### Một xung đột input cần lưu ý','',
        'Với mã v3.01 hiện có, plan yêu cầu TP1 gần hơn TP2 và RR1 ≥ MinRR. Profile lưu Hybrid TP2=2R nhưng MinRR=2: theo các bất đẳng thức danh nghĩa, vừa yêu cầu RR1<2 vừa RR1≥2. Vì vậy không thể lấy profile này làm bằng chứng các giao dịch cũ được phát bởi bộ CHoCH Pure R:R đã backtest. Việc dùng vùng cản để tự quyết định giao dịch là một khả năng, chưa được xác nhận bằng nhật ký tín hiệu.',
        '', '## 4. Giới hạn quy kết cho indicator','',
        f"Có một lệnh mang comment **ApexICT_AutoPreSession** (lệnh tháng 9); {s['n']-1} lệnh còn lại có comment vào lệnh trống. Indicator được load trên chart vào nhiều thời điểm, nhưng thiếu nhật ký tín hiệu gắn với từng entry. Không thể quy toàn bộ lãi/lỗ mẫu này cho riêng indicator.",
        '', f"Còn **{summary['unpaired_entry_objects']} mũi tên vào lệnh chưa tìm thấy exit tương ứng** trong chart lưu, nên chưa tính P&L của chúng. Các lần yêu cầu đóng bị báo Market closed không được coi là giao dịch đã khớp. Vì vậy mẫu lệnh đóng dương không đồng nghĩa equity hoặc toàn tài khoản cũng dương.",
        '', 'Timestamp chart và clock journal lệch khoảng bốn giờ, có độ trễ vài giây. Báo cáo giữ nguyên clock lưu; không dùng chúng để tự gán London/NY hoặc xác nhận giới hạn daily loss FTMO.',
        '', '## 5. Kết luận cập nhật','',
        '**Nhận xét “vài lệnh giao dịch cho hiệu suất tốt” có số liệu hỗ trợ trong mẫu chart này.** Kết quả đó có thể cùng tồn tại với một backtest dài hạn âm, và dữ liệu thực tế còn cho thấy cách giao dịch đang khác mô hình đã test.',
        '', 'Tôi thu hẹp kết luận trước: **cấu hình Pure R:R đã kiểm định không đạt trong mô phỏng đó; chưa đủ cơ sở loại bỏ toàn bộ cách bạn sử dụng indicator.** Phần đáng kiểm định riêng là vùng cản kết hợp cách chọn lệnh và quản lý SL/TP thực tế. Hiện chưa khôi phục đủ quy tắc chọn/bỏ tín hiệu, P&L ròng và drawdown để kết luận cách đó có thể pass quỹ.',
        '', '## 6. Bằng chứng đã lưu','',
        '- RECOVERED_CLOSED_TRADES.csv / .json: đầy đủ 22 cặp, giá, volume, P&L, thời gian và mức đối chiếu journal.',
        '- JOURNAL_FILLS.json / JOURNAL_MODIFICATIONS.json: các giá khớp và sửa SL/TP đọc được.',
        '- SAVED_PROFILE_INPUTS.json: chỉ các input liên quan chiến lược; loại token/chat ID.',
        '- ENTRY_OBJECTS_WITHOUT_RECOVERED_EXIT.json: các entry còn thiếu exit.',
        '- COLLECTION.json: phạm vi tài khoản API thực sự đọc được.',
        '- SOURCE_MANIFEST.json / SAVED_PRESET_CHECK.json: hash, kiểm tra số học và input.',
        '', 'File nguồn/binary indicator và tài khoản giao dịch được giữ nguyên. Không có lời khẳng định đây là lợi nhuận tiền thật hoặc lợi nhuận ròng của riêng indicator.','']
    (RUN/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    RUN.mkdir(parents=True,exist_ok=True);fixtures()
    profiles,arrows,connectors,errors=recover()
    fills,mods,close_requests,sources=journal()
    save('JOURNAL_FILLS.json',list(fills.values()));save('JOURNAL_MODIFICATIONS.json',mods)
    save('JOURNAL_CLOSE_REQUESTS.json',close_requests)
    rows=[];clock_offsets=[];unmatched=[]
    for pair in connectors.values():
        entry=arrows.get(pair['entry_ticket']);exit=arrows.get(pair['exit_ticket'])
        if entry is None or exit is None:
            unmatched.append(pair);continue
        assert entry['side']!=exit['side']
        assert math.isclose(entry['price'],pair['entry_price'],abs_tol=1e-6)
        assert math.isclose(exit['price'],pair['exit_price'],abs_tol=1e-6)
        assert entry['recorded_time']==pair['recorded_entry_time'] and exit['recorded_time']==pair['recorded_exit_time']
        direction=1 if entry['side']=='buy' else -1
        # Check the displayed profit with executed prices and inferred 100 oz/lot.
        calculated=direction*(exit['price']-entry['price'])*exit['volume']*100.
        assert math.isclose(calculated,pair['gross_profit'],abs_tol=.011)
        ef=fills.get(entry['ticket']);xf=fills.get(exit['ticket'])
        for item,arrow in [(ef,entry),(xf,exit)]:
            if item is None:continue
            assert item['side']==arrow['side'] and math.isclose(item['volume'],arrow['volume']) and math.isclose(item['price'],arrow['price'])
            naive_journal=datetime.fromisoformat(item['journal_clock']).replace(tzinfo=timezone.utc).timestamp()
            clock_offsets.append(arrow['recorded_time']-naive_journal)
        order=ef['order'] if ef else None
        changes=[m for m in mods if m['order']==order] if order is not None else []
        rows.append(dict(entry_ticket=entry['ticket'],exit_ticket=exit['ticket'],direction=entry['side'],
            opened_recorded_clock=iso(entry['recorded_time']),closed_recorded_clock=iso(exit['recorded_time']),
            entry_epoch=entry['recorded_time'],exit_epoch=exit['recorded_time'],entry_price=entry['price'],exit_price=exit['price'],
            entry_volume=entry['volume'],closed_volume=exit['volume'],gross_profit=pair['gross_profit'],exit_label=pair['reason'],
            entry_comment=entry['description'],exit_comment=exit['description'],
            entry_journal_matched=ef is not None,exit_journal_matched=xf is not None,
            entry_order=order,completed_modifications=len(changes),
            distinct_positive_TP=len({m['tp'] for m in changes if m['tp']>0}),
            distinct_positive_SL=len({m['sl'] for m in changes if m['sl']>0}),
            source=pair['source']))
    rows.sort(key=lambda x:x['exit_epoch']);table('RECOVERED_CLOSED_TRADES.csv',rows)
    save('RECOVERED_CLOSED_TRADES.json',rows);save('UNMATCHED_CONNECTORS.json',unmatched)
    exits={r['exit_ticket'] for r in rows};entries={r['entry_ticket'] for r in rows}
    unpaired=[x for k,x in arrows.items() if k not in exits and k not in entries]
    save('ENTRY_OBJECTS_WITHOUT_RECOVERED_EXIT.json',unpaired)
    counts=Counter(round(x) for x in clock_offsets)
    summary=dict(sample_scope='Only trades drawn on saved charts with recoverable complete entry/exit arrows and connector profit; not a complete account statement.',
        stats=stat(rows),days={day:stat([r for r in rows if r['closed_recorded_clock'].startswith(day)]) for day in sorted({r['closed_recorded_clock'][:10] for r in rows})},
        entry_comment_counts=dict(Counter(r['entry_comment'] or '(empty)' for r in rows)),
        fills_crosschecked=sum(r['entry_journal_matched'] for r in rows)+sum(r['exit_journal_matched'] for r in rows),
        full_volume_pairs=sum(math.isclose(r['entry_volume'],r['closed_volume']) for r in rows),
        positive_stop_exits=sum(r['exit_label']=='SL' and r['gross_profit']>0 for r in rows),
        trades_with_modifications=sum(r['completed_modifications']>0 for r in rows),
        unpaired_entry_objects=len(unpaired),unparsed_connectors=len(errors),missing_arrow_connectors=len(unmatched),
        journal_to_chart_clock_offsets_seconds={str(k):v for k,v in counts.items()},
        account_attribution='Current IPC account has no XAU history; chart/journal records belong to an older MetaQuotes-Demo account. This does not establish real-money P&L.',
        credentials_not_exported=True,source_profile_hashes=[dict(path=p['path'],sha256=p['sha256']) for p in profiles])
    save('SUMMARY.json',summary)
    frozen=json.loads((ROOT/'reports/gold_v301_causal/20261101/FROZEN_PLAN.json').read_text(encoding='utf-8'))
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==frozen['sources'][name]
                  for name in ['duc_tri_can_ho_tro.mq5','duc_tri_can_ho_tro.ex5'])
    assert unchanged
    save('SOURCE_MANIFEST.json',dict(journal_files=sources,profiles=summary['source_profile_hashes'],
        scripts={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in ['inspect_gold_live_history.py','review_gold_saved_trades.py']},
        parser_checks=True,executed_price_profit_checks=len(rows),current_account_history_error=False,
        original_indicator_unchanged=unchanged,credentials_excluded=True))
    report(rows,summary,profiles)
    print(json.dumps(summary,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
