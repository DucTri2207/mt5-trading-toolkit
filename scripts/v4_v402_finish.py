# -*- coding: utf-8 -*-
"""Audit the scoped fixes, collect chart evidence, and package a new immutable v4.0.2 ZIP."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import csv,json,hashlib,shutil,re,math,zipfile
ROOT=Path(__file__).resolve().parents[1];REL=ROOT/'can_ho_tro_v4'
RUN=ROOT/'reports/can_ho_tro_v4/20261102_v402_v1'
PORT=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def main():
    build=RUN/'build_final';comp=[]
    for name in ['COMPILE_EA_v402.log','COMPILE_indicator.log']:
        line=next(x for x in (build/name).read_text(encoding='utf-16').splitlines() if 'Result:' in x)
        assert '0 errors, 0 warnings' in line;comp.append('- '+name+': `'+line+'`.')
    for name,b in [('MQL5/Experts/CanHoTroV4_TesterEA.ex5','BUILD_v402.json'),('MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5','BUILD_indicator.json')]:
        assert sha(REL/name)==load(build/b)['binary_sha256']==sha(PORT/name)
    unitfiles=[('TestV402StorageRisk','v402_units.json',23),('TestV402IndicatorRisk','indicator_risk_result.json',11),('TestV401RiskStops','risk_stops_result.json',25)]
    for name,out,count in unitfiles:
        x=load(RUN/'units_final'/name/out);assert x['checks']==count and x['failures']==0
        assert load(RUN/'units_final'/('BUILD_'+name+'.json'))['passed']
    assert load(RUN/'units_final/TestV402IndicatorRisk/indicator_risk_result.json')['oracle_calls']==0
    chart=PORT/'MQL5/Files/v402_chart';assert load(chart/'done.json')['completed']
    stages=rows(chart/'stages.csv');assert [x['stage'] for x in stages]==['H1_first','M5_first','M15','M5_return','M5_reattach','M5_recovered']
    assert all(x['indicator_count']=='1' for x in stages)
    keys=['M5_first','M5_return','M5_reattach'];arrows=[sorted(rows(chart/(k+'_arrows.csv')),key=lambda x:x['name']) for k in keys]
    assert len(arrows[0])==29 and arrows[0]==arrows[1]==arrows[2]
    risk=rows(chart/'risk_expected.csv')[0];equity=float(risk['equity']);distance=abs(float(risk['entry'])-float(risk['sl']))
    assert risk['profit_ccy']==risk['account_ccy']=='USD' and float(risk['contract'])==100
    perlot=distance*float(risk['contract']);target=equity*float(risk['percent'])/100;step=float(risk['step'])
    expected=max(float(risk['min_lot']),math.floor(min(target/perlot,float(risk['max_lot']))/step+1e-10)*step)
    for stage in stages:
        if stage['stage'] in keys:
            actual=float(re.search(r'Lot ([0-9.]+)',stage['lot_panel']).group(1));assert abs(actual-expected)<1e-9
            assert abs(target-actual*perlot)<=perlot*step+1e-8
            assert stage['risk_warning']=='broker khai báo tick value không khớp'
    recovery=stages[-1];assert recovery['recovery_warning'] and recovery['risk_warning']==recovery['recovery_warning']
    out=RUN/'chart_final/outputs';shutil.copytree(chart,out)
    launch=load(RUN/'chart_final/LAUNCH.json');log=[]
    for p in (PORT/'MQL5/Logs').glob('*.log'):
        text=p.read_bytes()[launch['log_offsets'].get(str(p),0):].decode('utf-16-le',errors='replace')
        log.extend(x for x in text.splitlines() if any(t in x for t in ['TestV402Chart','duc_tri_can_ho_tro_v4','V402_','V4_']))
    (RUN/'chart_final/EXPERTS.filtered.log').write_text('\n'.join(log)+'\n',encoding='utf-8')
    assert not any('V4_RISK_FAIL_CLOSED' in x or 'V4 deferred ledger failed' in x or 'V402_CHART_FAIL' in x for x in log)
    assert sum('V4_LEDGER_RECOVERED' in x for x in log)==1 and any('V402_CHART_DONE' in x for x in log)
    archive=RUN/'chart_final/quarantined_files';archive.mkdir()
    archived=[]
    for line in log:
        if 'V4_CORRUPT_ARCHIVED ' in line:
            rel=line.split('V4_CORRUPT_ARCHIVED ',1)[1];p=PORT/'MQL5/Files'/rel
            assert p.is_file() and str(p.resolve()).startswith(str((PORT/'MQL5/Files').resolve()))
            shutil.copy2(p,archive/p.name);archived.append(dict(path=rel,sha256=sha(p)))
    assert len(archived)>=5
    changed=[];unchanged=[];before=RUN/'before/MQL5'
    for p in (REL/'MQL5').rglob('*'):
        if p.is_file() and p.suffix!='.ex5':
            old=before/p.relative_to(REL/'MQL5')
            if not old.exists() or sha(old)!=sha(p):changed.append(p.relative_to(REL/'MQL5').as_posix())
            else:unchanged.append(dict(path=p.relative_to(REL).as_posix(),sha256=sha(p)))
    allowed={'Experts/CanHoTroV4_TesterEA.mq5','Indicators/duc_tri_can_ho_tro_v4.mq5'}|{'Include/CanHoTroV4/'+x for x in ['Identity.mqh','Logger.mqh','Scorecard.mqh','Risk.mqh','M2Panel.mqh']}
    assert set(changed)==allowed,changed
    assert all(sha(p)==sha(RUN/'before/Presets'/p.name) for p in (REL/'Presets').iterdir() if p.is_file())
    audit=dict(version='4.0.2',passed=True,unit_checks=59,unit_failures=0,indicator_oracle_calls=0,chart_sequence=[x['stage'] for x in stages],actual_production_indicator=True,initial_attachment='terminal Insert/Indicators/Custom menu',reattach='saved production chart template, drawing objects removed; indicator inputs unchanged',accepted_broker_seed=29,arrows_unchanged=29,equity=equity,entry=float(risk['entry']),sl=float(risk['sl']),contract=100,profit_ccy='USD',account_ccy='USD',risk_percent=.5,target_cash=target,risk_per_lot=perlot,lot=expected,actual_risk_cash=expected*perlot,error_cash=target-expected*perlot,one_step_cash=perlot*step,corrupt_recovery=True,archived_files=archived,changed_source=changed,unchanged_source=unchanged,presets_unchanged=True,real_terminal_D0E8209F_accessed=False,M3b_HIST_rerun=False)
    dump(RUN/'RESULTS_V402.json',audit)
    report='''# v4.0.2 — ĐẠT kiểm tra hai lỗi chạy indicator thật; chờ Claude nghiệm thu

## Đã làm

Đọc README_QUY_UOC,claude_003,claude_012,claude_013; không đọc chat cũ. Phạm vi khóa ở SCOPE_LOCK.json. Chỉ sửa namespace/checkpoint recovery và risk trong indicator; detector,scale,RR,preset input giữ nguyên. EA chỉ đổi version metadata, logic sizing vẫn OrderCalcProfit. Không chạm terminal thật D0E8209F: mọi compile/chart chỉ ở portable20261102_m3a_v1 hoặc native test biệt lập.

### 1. Checkpoint

V4Preset resolve PERIOD_CURRENT thành HTF/LTF thực, thêm chart period (ATR chart) và UseLtfConfirm. File signals/state/candidates/guard_rejects có symbol+fingerprint; score có fingerprint này và hash cost/account. Không đọc legacy symbol-only và không dùng state của cấu hình khác. Sửa so sánh ID rỗng/NULL khi cấu hình chưa có signal; nếu không sửa, state rỗng hợp lệ cũng có thể bị coi là inconsistent.

State/ledger hỏng của chính cấu hình: đóng handle không ghi đè state lỗi, đổi tên bộ liên quan thành *_corrupt_<time>,reset runtime,khởi tạo lại. Score cùng fingerprint cũng archive; file cấu hình khác và legacy giữ nguyên. Cảnh báo đỏ trong panel và nhãn chart bên phải; log có đường dẫn archive. Lỗi khóa mở file không được coi là corruption, giữ cơ chế chờ writer có giới hạn. Chưa bảo đảm transaction nguyên tử giữa mọi file hoặc phục hồi tự động archive.

### 2. Risk indicator

Nhánh PROGRAM_INDICATOR dùng contract size × adverse price distance × lot × tỷ giá profit→account. Cùng tiền rate1; khác tiền tìm symbol direct/inverse theo currency metadata (có suffix), hoặc bridgeUSD. Tiền lỗ dùng ask direct/1-bid inverse. Thiếu contract/currency/symbol/quote hợp lệ thì Lot N/A rõ lý do; không tick fallback. EA/script giữ OrderCalcProfit. Công thức tick đối chiếu lệch>1% vẫn cảnh báo đúng câu. Cost/R và journal dùng cùng nguồn tiền theo frontend. Không đổi volume step/min/max/0.5% preset.

## Kiểm thật trên chart portable

Indicator ex5 sản xuất4.02 được gắn trực tiếp bằng menu Insert→Indicators→Custom trên H1, không đổi callback hoặc adapter. Controller MQL chỉ điều khiển chart/thu object bằng API; H1→M5→M15→M5→gỡ/gắn lại. Lần gắn lại dùng template của indicator thật, bỏ object vẽ đã lưu để không che nhãn mới; input giữ mặc định. Native 59 checks bổ sung, không thay kiểm chart.

Để kiểm persistence không rỗng mà không đổi detector/preset, nạp29 signal broker đã có từ run v4.0.1 vào bộ M5 mới, checkpoint tại bar hiện tại. Đây là seed lịch sử hợp lệ, không phải29 signal mới phát hiện trong phiên live. Tại M5_first,M5_return,M5_reattach: cùng29 tên/time/price mũi tên, một indicator; H1/M15 rỗng và không đọc nhầm state M5.

Equity demo10000USD,risk0.5%,entry4034.36,SL4027.158,contract100,step0.01: risk/lot720.20,target50USD; panel lot0.060,risk43.21USD (cash43.212),lệch6.788USD≤một bước7.202USD. Panel có “broker khai báo tick value không khớp”, không OrderCalcProfit failure. QA tài khoản thật trong portable chỉ USD/USD; FX path kiểm unit, chưa live QA account khác tiền.

Chủ ý làm sai checkpoint M5 của bộ test sau khi đã kiểm giữ arrows: bộ riêng được archive (signals/state/candidates/guard/score),runtime khởi tạo lại,indicator tiếp tục chạy,panel/chart hiện rõ “Đã cách ly ledger/state lỗi; khởi tạo lại.”. Screenshot M5_recovered.png và log V4_LEDGER_RECOVERED/V402_CHART_DONE có thật. Sau recovery không tự nhập29 signal archive trở lại. Đóng portable để flush state/log sau QA,không gửi lệnh.

## Output kiểm tra cuối

'''+ '\n'.join(comp)+'''

- Storage/lifecycle/risk:23 checks/0 failures; resolve CURRENT==explicit,H1/M5/M15 isolation,empty state,reload nonempty,corrupt archive+warning,other config unchanged,direct/inverse FX and invalid quotes.
- Indicator risk:11 checks/0 failures,oracle_calls0;contract sizing/cost,mismatch warning,missing FX/contract/currency fail closed,and retry after metadata ready.
- EA risk/trail regression:25 checks/0 failures;×10 oracle case,failed/positive/NaN oracle,lot rounding/cost,normalized no-op,stops/freeze. Mỗi script compile0/0.
- Không chạy lại full-prefix,HIST,M3b hoặc P&L:detector/scale/RR không đổi. Baseline v4.0.1 được giữ cùng hash ZIP,không coi là kết quả v4.0.2 mới. Không M4/M5.

## Lỗi phát triển và giới hạn

Test đầu phát hiện NULL/empty ID mismatch và assertion float exact,đã sửa và chạy lại native final. Hai lượt controller iCustom đầu không dùng làm gate chart:handle vẽ trên chart gọi và profile còn giữ writer;gate cuối gắn qua UI thật. Template ban đầu chứa drawings che labels;gate cuối bỏ drawings trước reattach và kiểm hình thật. Một cảnh báo recovery lúc đầu bị dashboard che;binary cuối đặt bên phải và panel line10,đã chạy lại toàn chuỗi/kiểm hình.

Lỗi thật của v4.0.1 đã sửa trong phạm vi; không blocker còn mở. Chưa QA FX nhiều loại tài khoản/instrument phi tuyến,stale quote/currency lịch sử,journal broker,partial fill,forward,DST,Telegram hoặc crash transaction. Không có kết luận lợi thế; baseline HIST/tick thật trước đều âm. v4.0 M3a vẫn KHÔNG được phát hành vì lot×10;v4.0.1 được thay bằng v4.0.2 do hai lỗi runtime.

## Đóng gói và điểm dừng

Gói CanHoTro_v4.0.2.zip gồm mq5/mqh/ex5,preset không đổi,HUONG_DAN_KY_THUAT,CHANGELOG,validation/v402 và baseline chọn lọc. Internal manifest hash payload;external manifest hash ZIP;giải nén vào thư mục mới,CRC và hash mọi file. Không chứa executable terminal/account config. Không cài vào terminal thật. Script v4_v402_finish.py lưu cách audit/package;controller+nguồn unit+log+CSV+PNG trong validation.

Ghi codex_outbox/codex_009_v402.md rồi DỪNG chờ Claude nghiệm thu; không mở mốc khác.
'''
    (RUN/'REPORT.md').write_text(report,encoding='utf-8')
    # Preserve previous validation outside the current payload; all paths verified inside workspace.
    previous=(REL/'validation').resolve();snapshot=(RUN/'validation_v401_snapshot').resolve()
    assert previous.parent==REL.resolve() and snapshot.parent==RUN.resolve() and not snapshot.exists();previous.rename(snapshot)
    val=REL/'validation/v402';val.mkdir(parents=True)
    for name in ['REPORT.md','RESULTS_V402.json','SCOPE_LOCK.json']:shutil.copy2(RUN/name,val/name)
    for folder in ['build_final','units_final','chart_final']:
        dst=val/folder;dst.mkdir()
        for p in (RUN/folder).iterdir():
            if p.name in ['portable_terminal'] or p.name.startswith('source_'):continue
            if p.is_dir():shutil.copytree(p,dst/p.name)
            else:shutil.copy2(p,dst/p.name)
    src=val/'sources';src.mkdir()
    for name in ['TestV402Chart.mq5','TestV402StorageRisk.mq5','TestV402IndicatorRisk.mq5','TestV401RiskStops.mq5','TestV4Core.mq5','FixtureData.mqh']:shutil.copy2(ROOT/'tests/v4'/name,src/name)
    for name in ['v4_v402_finish.py','v4_v402_docs.py','v4_v401.py','v4_m3b.py','v4_build_m1.py']:shutil.copy2(ROOT/'scripts'/name,src/name)
    for name in ['PlanStateV301.mqh','KillzoneV301.mqh']:shutil.copy2(RUN/'units_final/portable_terminal/MQL5/Scripts/V4'/name,src/name)
    base=REL/'validation/accepted_v401';base.mkdir()
    old=ROOT/'reports/can_ho_tro_v4/20261102_v401_final_v1'
    oldzip=old/'CanHoTro_v4.0.1.zip';assert sha(oldzip)=='3613b63cd859f276738ff5d048f2e88598b52773c6188781951b8f7497a7d7f5'
    for name in ['RESULTS_FINAL.json','RISK_EXECUTION_AUDIT.json','ZIP_VERIFICATION.json']:shutil.copy2(old/name,base/name)
    shutil.copytree(ROOT/'reports/can_ho_tro_v4/20261102_v401_v1/native_hist/outputs',base/'hist')
    shutil.copy2(ROOT/'reports/can_ho_tro_v4/20261101_m1_v2/DIFF_V301_V4.csv',base/'DIFF_V301_V4.csv')
    dump(base/'BASELINE.json',dict(version='4.0.1',not_rerun_in_v402=True,zip_sha256=sha(oldzip)))
    payload=[dict(path=p.relative_to(REL).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(REL.rglob('*')) if p.is_file() and p!=REL/'MANIFEST.json']
    dump(REL/'MANIFEST.json',dict(version='4.0.2',status='scoped tests passed; awaiting Claude acceptance',files=payload))
    zipath=RUN/'CanHoTro_v4.0.2.zip';assert not zipath.exists()
    with zipfile.ZipFile(zipath,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(REL.rglob('*')):
            if p.is_file():z.write(p,'can_ho_tro_v4/'+p.relative_to(REL).as_posix())
    extracted=RUN/'extracted_verification';extracted.mkdir()
    with zipfile.ZipFile(zipath) as z:
        assert z.testzip() is None and all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist());z.extractall(extracted)
    actual=extracted/'can_ho_tro_v4';files=[p for p in REL.rglob('*') if p.is_file()]
    assert len(files)==len([p for p in actual.rglob('*') if p.is_file()])
    assert all(sha(p)==sha(actual/p.relative_to(REL)) for p in files)
    assert all(sha(actual/x['path'])==x['sha256'] for x in payload)
    dump(RUN/'ZIP_VERIFICATION.json',dict(passed=True,files=len(files),payload_files=len(payload),mismatches=[],CRC_passed=True,zip_sha256=sha(zipath),v401_zip_unchanged_sha256=sha(oldzip)))
    evidence=[dict(path=p.relative_to(RUN).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(RUN.rglob('*')) if p.is_file() and 'portable_terminal' not in p.parts and 'extracted_verification' not in p.parts and p.name not in ['MANIFEST.json','MANIFEST_VERIFICATION.json']]
    dump(RUN/'MANIFEST.json',dict(version='4.0.2',zip=dict(path=zipath.name,sha256=sha(zipath)),files=evidence))
    assert all(sha(RUN/x['path'])==x['sha256'] for x in evidence)
    dump(RUN/'MANIFEST_VERIFICATION.json',dict(passed=True,files=len(evidence),mismatches=[]))
    proof='\n'.join('- `'+(RUN/n).relative_to(ROOT).as_posix()+'` — SHA-256 `'+sha(RUN/n)+'`' for n in ['CanHoTro_v4.0.2.zip','REPORT.md','RESULTS_V402.json','MANIFEST.json','ZIP_VERIFICATION.json','MANIFEST_VERIFICATION.json'])
    out='''# codex_009 — v4.0.2 — ĐẠT kiểm tra hai lỗi, chờ Claude nghiệm thu
Đã đọc README_QUY_UOC,claude_003,claude_012,claude_013; không đọc chat cũ.
Thời điểm: '''+datetime.now(timezone(timedelta(hours=7))).isoformat()+'''

## Đã làm

- Ledger/state/candidates/guard/score tách theo fingerprint đã resolve HTF/LTF và chart period. Sửa NULL/ID rỗng. Không đọc state cấu hình khác/legacy symbol-only.
- Bộ riêng corrupt được archive *_corrupt_<time>,reset,khởi tạo lại;cảnh báo đỏ nhìn thấy trên chart/panel. Không archive vì lock/I/O. Giữ dữ liệu bộ khác.
- Indicator dùng contract size×price distance×lot×FX; direct/inverse/USD bridge,cùng tiền rate1; thiếu metadata/quote fail closed rõ lý do. Tick mismatch vẫn cảnh báo; EA tiếp tục OrderCalcProfit. Detector/scale/RR/preset không đổi.
- Indicator sản xuất thật qua menu H1 trên portable20261102_m3a_v1; H1→M5→M15→M5→gỡ/gắn;29 mũi tên M5 giữ nguyên tên/time/price.29 signal seed lấy ledger broker cũ để test persistence,không phải tín hiệu mới trong phiên. Gắn lại dùng template sạch drawings,input không đổi.
- Panel thật equity10000USD,target50USD,entry4034.36/SL4027.158,contract100,step.01:lot.060,risk43.212USD,lệch6.788USD≤1 bước7.202USD. Cảnh báo tick mismatch hiện; không OrderCalcProfit failure. Chủ ý corrupt checkpoint riêng:archive≥5 file,running lại,cảnh báo hiện rõ; PNG/log/CSV kèm theo.
- Native final:storage23/23,indicator risk11/11 (oracle calls0),EA risk/trail25/25,tổng59/59. Compile EA+indicator+controller+unit0/0. Không truy cập hoặc thao tác terminal D0E8209F,không gửi lệnh.
- Đóng gói4.0.2 source/binary,preset,docs,validation,manifest+ZIP;CRC+hash sau giải nén đạt. ZIP4.0.1 cũ giữ nguyên.

## Bằng chứng

'''+proof+'''

### Output thật cuối

'''+ '\n'.join(comp)+'''
- Storage: `{"checks":23,"failures":0}`.
- Indicator: `{"checks":11,"failures":0,"oracle_calls":0}`.
- EA regression: `{"checks":25,"failures":0}`.
- Chart: `{"completed":true,"actual_production_indicator":true,"recovery_warning":true}`.

## Lệch / giới hạn

Không blocker còn mở trong hai lỗi. Không chạy lại M3b/HIST/full-prefix/P&L vì detector/scale/RR không đổi;baseline cũ được ghi rõ không chạy mới. FX khác tiền kiểm unit,chưa live account khácUSD;không bảo đảm contract model mọi instrument phi tuyến hoặc currency lịch sử. Recovery không nhập archive,tính nguyên tử nhiều file/crash chưa bảo đảm. Lượt controller iCustom/template có drawings ban đầu chỉ là debug;gate cuối gắn UI thật,template bỏ drawings,cảnh báo đã kiểm hình. Báo cáo đầy đủ REPORT.md ghi giới hạn.

## Điểm dừng

Đã ghi báo cáo và đóng gói. DỪNG chờ Claude nghiệm thu;không M4/M5,không bật heartbeat.
'''
    (ROOT/'codex_outbox/codex_009_v402.md').write_text(out,encoding='utf-8')
    print(json.dumps(dict(version='4.0.2',zip_sha256=sha(zipath),files=len(files),checks=59,chart_verified=True,hash_verified=True)))
if __name__=='__main__':main()
