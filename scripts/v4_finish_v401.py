# -*- coding: utf-8 -*-
from pathlib import Path
import json,csv,hashlib,shutil,statistics
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'reports/can_ho_tro_v4/20261102_v401_v1';REL=ROOT/'can_ho_tro_v4'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
assert load(RUN/'PREFIX_401_SUMMARY.json')['totals']=={'0':200,'1':200}
assert load(RUN/'units/scale_units.json')=={'checks':17,'failures':0}
assert load(RUN/'native_hist/outputs/hist_result.json')['failures']==0
assert load(RUN/'POSITIVE_PARITY.json')['matched']==29
summary=load(RUN/'STATS_PRELIMINARY.json');summary['tester']=load(RUN/'TESTER_METRICS.json');summary['risk_audit']=load(RUN/'RISK_DENOMINATOR_AUDIT.json');summary['deal_relation_R']=load(RUN/'DEAL_R_RECONCILIATION.json')
summary['TRAIL_TRAIL']['valid_baseline']=False;summary['TRAIL_TRAIL']['termination']='TesterStop after redundant initial SL/TP modification returned Invalid stops; tester forced close'
summary['gate_status']=dict(scaling=True,prefix=True,compile=True,HIST=True,positive_signal_parity=True,M3b_full=False,release_zip_replaced=False)
dump(RUN/'RESULTS_V401.json',summary)
# Freeze the exact positive-parity adapter/fixture source for review without terminal files.
evidence=RUN/'validation_sources';evidence.mkdir()
for name in ['v4_v401.py','v4_m3b.py','v4_build_m1.py','v4_port_m1.py','v4_finish_v401.py']:
    shutil.copy2(ROOT/'scripts'/name,evidence/name)
for name in ['TestV401Hist.mq5','TestV401ScaleUnits.mq5','TestV4Core.mq5','FixtureData.mqh','TestV4Acceptance.mq5']:
    shutil.copy2(ROOT/'tests/v4'/name,evidence/name)
for name in ['TestV401Prefix0.mq5','TestV401Prefix1.mq5','PlanStateV301.mqh','KillzoneV301.mqh']:
    shutil.copy2(RUN/'prefix_r2_worker_0/portable_terminal/MQL5/Scripts/V4'/name,evidence/name)
for name in ['Market401.mqh','Indicator401.mqh']:shutil.copy2(RUN/'native_hist/portable_terminal/MQL5/Scripts/V4'/name,evidence/name)
frozen=ROOT/'reports/can_ho_tro_v4/20261101_m2_v1/portable_terminal/MQL5/Files/v4_fixture'
dump(RUN/'FROZEN_INPUTS.json',[dict(path=(frozen/n).relative_to(ROOT).as_posix(),bytes=(frozen/n).stat().st_size,sha256=sha(frozen/n)) for n in ['h1.csv','m5.csv','m1.csv']])
compile_quotes=[]
for name in ['COMPILE_EA_v401.log','COMPILE_indicator.log','COMPILE_indicator_adapter.log']:
    lines=(RUN/name).read_text(encoding='utf-16').splitlines();compile_quotes.extend(name+': '+x.strip() for x in lines if 'Result:' in x)
report="""# v4.0.1 — Scaling/prefix/HIST/parity đạt; M3b CHƯA ĐẠT, chưa thay ZIP

Đã thực hiện đúng hệ số khóa trước, không thử hệ số/preset khác. EXIT_1R và indicator chạy hết4 tháng tick thật, có29 tín hiệu khớp toàn31 cột. TRAIL dừng fail closed ở lệnh đầu do lỗi modify đã tồn tại. Kiểm risk từ deal còn phát hiện mẫu số tiền risk trong ledger thấp10x. Không sửa hai đường thực thi/risk ngoài phạm vi “không thay đổi gì khác” của claude_010. Checkpoint codex_007_v401_blocker.md đã báo để Claude quyết định riêng. Không có chỉ thị mới khi hoàn tất. Không M4/M5.

## Khóa và thay đổi
LOCK_V401.json được ghi trước chạy P&L. InpPriceScaleMode=0 giữ khoảng cách/preset hash v4.0;=1 mặc định áp dụng cho symbol có XAU. k=close D1 đã đóng gần nhất /2000. Production dùng iBarShift(at) và CopyRates D1 shift+1; không dùng forming D1 hoặc close hiện tại. Thiếu D1: chờ dữ liệu/đánh dấu MISSING_CLOSED_D1 trong HIST, không ngầm fallback1. Các symbol khác giữ k1.
PRICE_SCALE_INPUT_MAP.csv ghi đủ9 input: MaxSlPips,MinSlPips,InpTp1Pips,InpTp2Pips,InpBeTriggerPips,InpBeOffsetPips,MaxSpreadPrice,InpHistSpreadPrice,InpSlippagePoints. INPUT_MAP gốc không có input “gần cản” giá tuyệt đối khác; các khoảng gần cản trong detector theo ATR giữ nguyên. Pip size0.1 là đơn vị, không đổi; khoảng tính từ pip mới nhân k. Commission/tiền tài khoản/%risk/ATR/RR/số nến/điểm/UI pixels không nhân.
BE trigger theo D1 tại observation; BE offset được đóng băng vào bePrice lúc tạo signal, không sửa lại SL/TP đã có khi sang ngày. HIST spread và slippage model theo k tại fill/exit bar; LIVE slip model theo tick. Spread quote và deal commission/swap/fee thực không nhân. EA deviation tolerance theo k mỗi tick, không giả lập fill/slippage thêm. Không đổi MinRR, TP mode, bộ lọc hoặc giá trị base trong defaultset; chỉ thêm mode1.
PriceScale.mqh mới, dùng qua Time.mqh; Signals/LogicHelpers/Observation/Scorecard/M2Panel/EA nối các khoảng đúng chỗ. Identity preset mode1 có dấu PRICE_SCALE_D1_2000 để không trộn state; mode0 key cũ. Input validation0/1. MQL version4.01 biểu diễn sản phẩm4.0.1. Risk.mqh,Execution.mqh,Zones.mqh nguyên hash trước/sau (UNCHANGED_SCOPE_CHECK.json).

## Gates đã đạt
- Indicator, EA, adapter callbacks:0 errors/0 warnings, log compiler thật kèm theo.
- M1 prefix:200/200 mode0 và200/200 mode1; seed20261101,4 partition50/mode, mỗi case chạy độc lập theo cutoff. Giữ profile M1 RR/market/reference=false để regression, không dùng P&L để chọn cutoff. Mode0 giữ profile/control cũ; mode1 cùng cutoff với scale D1 causal. Đây là prefix M1, không đổi thành default-profile khác.
- Scale units:17 checks/0 failures (mode0 khi thiếu D1; mode1 không có D1 thì reject; D1 ngày trước/ranh ngày; thay close forming/future không đổi k; cả9 khoảng ×2).
- HIST:1519 checks/0 failures, gồm200 thời điểm scale với3 checks mỗi thời điểm, mutate close H1 tương lai không đổi k; các check time-order fill/exit.
- Parity dương29/29 tín hiệu EA ↔ indicator,31 cột,0 mismatch. Dùng adapter gọi callback sản xuất OnInit/OnCalculate/OnTimer/OnDeinit trong nonvisual tester như M3b trước; UI/notification tắt và helper Telegram config no-op trong bản sao. Không phải visual tester; không kiểm mỹ thuật. Production detector/plan/scale dùng chung, không mock tín hiệu.

## M3b tick thật, cùng config khóa
Portable được chỉ định, session demo do người dùng đăng nhập; không đọc/sửa/copy account config, không login hoặc chạm MT5 thật. MetaQuotes-Demo, terminal6296, XAUUSD M5,Model4,01/07/2026–31/10/2026 end exclusive,deposit100000USD,leverage100,InpRiskPercent0.5,mode1, các baseinput khác giữ mặc định.

| Kết quả | EXIT_1R hết kỳ | TRAIL bị ngắt |
|---|---:|---:|
| Ticks; quality |44.373.721;100% real|4.055.862;100% real tới lúc dừng|
| Signal / closed |29/29|1/1 forced-close khi TesterStop|
| Win net |37.931034%|không dùng làm baseline|
| Mean gross R theo cash relation deal |−0.1669473524|không dùng làm baseline|
| Mean net R theo cash relation deal |−0.1699988659|không dùng làm baseline|
| PF_R cùng mẫu số deal |0.7466965167|không dùng làm baseline|
| Net USD |−26.743,06|−145,82 (forced close)|
| Max equity DD tester |43.201,44USD;40,06%|145,82USD;0,15% đến khi dừng|
| Exit reasons |SL17,TP_1R11,TIMEOUT1|raw exit_reason trống; stop do invalid stops|

Phí EXIT_1R lấy từ history deals qua ledger: commission0,fee0,swap−438.97USD; broker defaults giữ nguyên, không khẳng định đã cấu hình commission7. Input7 là mô hình ảo, không override phí tester. Entry quote spread khôi phục từ cost_R/risk_price và các phí tách riêng: min0.14,mean0.315172414,max0.64 đơn vị giá; đó là spread snapshot quote tại entry, không phải trường spread có sẵn trong deal. Toàn stream tick hợp lệ mean0.3281015,max148.91, không scale spread thực. Không suy slippage riêng từ signal close; thiếu request-quote/deal audit để tách chính xác.

### Blocker1 — TRAIL
Lệnh đầu09/07 19:05,SELL6.34 @4125.79,SL4133.67 khớp. Initial PositionModify gửi cùng SL4133.67,TP0→SL4133.67,TP0, broker Invalid stops; EA TesterStop. EXIT_1R cùng entry sửa TP4117.91 thành công. CSV/log gốc trong v401_trail/. Chưa bỏ no-op modify hoặc đổi handling vì ngoài phạm vi scaling; chưa có kết quả TRAIL đủ kỳ. Không gộp forced close vào hiệu quả chiến lược.

### Blocker2 — cash risk/lot và R ledger
29 gross deal đều khớp (exit−entry)*side*volume*100, max lỗi4.72e−10USD. Initial risk theo cùng cash relation =risk_price*volume*100, đúng10x risk_USD ledger ở mọi29 dòng. Ví dụ lệnh đầu risk7.88×6.34×100=4995.92USD, ledger499.592USD; ý định0.5% thành xấp xỉ5% trên broker này. TickValueLoss/TickSize hiện dùng không khớp cash P&L broker. Không sửa Risk.mqh sang OrderCalcProfit trong scope này.
Raw ledger mean gross/net R=−1.669473524/−1.699988659 bị phóng đại10x; bảng trên dùng mẫu số tính lại từ cash relation deal, chi tiết DEAL_R_RECONCILIATION.csv/JSON. Đây là đối soát hậu nghiệm cho XAUUSD/USD có cash relation100 được kiểm cả29 dòng, chưa là kiểm OrderCalcProfit prospective hoặc sửa lots. DD40.06% là DD thật của run sizing sai; không chia10 để dự đoán DD tại0.5%. B0v4.0.1 đúng risk0.5% vẫn chưa được kiểm chứng.

## HIST toàn fixture2021–2026, mode1/default
Dữ liệu đóng băng M1 từ27/09/2021 01:05 đến23/10/2026 22:59 (timestamp server danh nghĩa), không có01–09/2021 hoặc24–31/10/2026. Chạy toàn bộ phần có sẵn; không bịa dữ liệu thiếu. D1 fixture tổng hợp từ H1 đã đóng của ngày lịch trước; production dùng D1 broker thật. Fixture không thay được QA DST/D1 broker cho cả2021–2026. Cùng engine V4HistEvaluate/M2, defaultHYBRID,reference=true,mode1;1mOHLC SL-first khi ambiguous,timeout theo đồng hồ. Cost model .30*k giá spread,1*k point slip,7 account-currency/lot roundtrip. Native GoldSpec tiền100 mỗi đơn vị giá/lot,không dùng tickvalue sai của run broker.

| HIST (459 signals/459 closed mỗi rule) | EXIT_1R | TRAIL |
|---|---:|---:|
| Win net % |43.790850|43.355120|
| Mean gross R |−0.025948576|−0.032347739|
| Mean net R |−0.130061607|−0.136460770|
| PF_R |0.752869416|0.741521351|
| Reasons |SL223,TP_1R161,TIMEOUT53,GAP22|SL359,TIMEOUT73,GAP27|

HIST và tick thật đều chưa cho bằng chứng lợi thế. Không gán thay đổi1393→459 riêng cho scale: fixture M2 cũ dùng profileRR/reference=false, bản này defaultHYBRID/reference=true. Không tối ưu hoặc thử hệ số khác sau số âm.

## Bàn giao và dừng
Source/binary/preset mode1 trong can_ho_tro_v4; bản chụp patch/ ở run này; nguồn test/runner ở validation_sources/,frozen hashes ở FROZEN_INPUTS.json; LOCK_V401,all CSV/JSON,HTML/.ini/.set/log cuối có manifest+kiểm hash. Không đóng đè ZIP v4.0 M3a đã nghiệm thu. Không cài terminal thật. Phần prefix harness lúc đầu vướng generator RR-trace cũ (không chạy strategy); setupnative riêng r2 đã sửa; unit lần1 có5 warning shadow tên n,lần2 đổi tên test vàcompile0/0. Giữ chứng cứ lỗi phát triển, chỉ dùng gate cuối.
Claude cần quyết định riêng về hai blocker trước khi mở sửa adapter/risk; Codex dừng sau codex_007_v401.md, không tự mở M4/M5 hoặc heartbeat.
"""
(RUN/'REPORT.md').write_text(report,encoding='utf-8')
for name in ['HUONG_DAN_KY_THUAT.md','CHANGELOG_V4.md']:
    p=REL/name;s=p.read_text(encoding='utf-8');s+='\n\n## v4.0.1 — đang chờ nghiệm thu\nInpPriceScaleMode=1 mặc định:9 input khoảng cách XAU ×close D1 đã đóng/2000;mode0 giữ v4.0. Commission/%/ATR/RR/số nến/điểm không đổi. Dùng thư mục ledger mới khi đổi mode; không trộn state. Giá trị input base không đổi, BE offset đã lưu theo signal-time, trigger theo observation-time. HIST model spread/slip scale tại fill/exit; quote/deal fees thực không nhân. Các dòng UI nhắc giá trị base input không thay thế giá BE/SL/TP thực đã tính trên signal.\nPrefix200/200 mỗi mode; parity dương29/29, HIST459 signals với ròng âm cả hai rule. M3b chưa đạt:TRAIL invalid stops ở redundant initial modify; risk_USD ledger thấp10x relation cash deal, run intended0.5% thực xấp xỉ5%,DD40.06%. Không dùng R ledger thô. Chưa sửa ngoài scope hoặc thay ZIP. Chi tiết reports/can_ho_tro_v4/20261102_v401_v1/REPORT.md và codex_outbox/codex_007_v401.md.\n';p.write_text(s,encoding='utf-8')
dump(REL/'MANIFEST.json',dict(version='4.0.1',status='review pending; M3b blockers',files=[dict(path=p.relative_to(REL).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(REL.rglob('*')) if p.is_file() and p.name!='MANIFEST.json']))
shutil.copytree(REL,RUN/'patch')
old=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/CanHoTro_v4.0_M3a.zip';assert sha(old)=='f515b8565e8b63cb64c27b8b12dea6e4457ec0d4190dd9fa330d17e6c32cdbf6'
files=[dict(path=p.relative_to(RUN).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(RUN.rglob('*')) if p.is_file() and 'portable_terminal' not in p.parts and p not in [RUN/'MANIFEST.json',RUN/'MANIFEST_VERIFICATION.json']]
dump(RUN/'MANIFEST.json',dict(version='4.0.1',files=files,release_zip_unchanged_sha256=sha(old)))
errors=[x['path'] for x in files if sha(RUN/x['path'])!=x['sha256']];assert not errors
dump(RUN/'MANIFEST_VERIFICATION.json',dict(files=len(files),mismatches=errors,passed=True))
proof='\n'.join('- `'+(RUN/n).relative_to(ROOT).as_posix()+'` — `'+sha(RUN/n)+'`' for n in ['LOCK_V401.json','REPORT.md','RESULTS_V401.json','PREFIX_401_SUMMARY.json','POSITIVE_PARITY.json','RISK_DENOMINATOR_AUDIT.json','MANIFEST.json','MANIFEST_VERIFICATION.json'])
out=f"""# codex_007 — v4.0.1 — CHƯA ĐẠT M3b; scaling/prefix/HIST/parity ĐẠT
Đã đọc claude_010,tuân thủ claude_003 và giới hạn trước; không đọc chat cũ.
Thời điểm: {datetime.now(timezone(timedelta(hours=7))).isoformat()}

## Đã làm
- Khóa LOCK_V401 trước P&L; mặc định InpPriceScaleMode1,k=close D1 đã đóng/2000,mode0 giữ khoảng cách và preset hash cũ. Rà INPUT_MAP:9 input giá/pip/point (SLmin/max,TP1/2 cố định,BEtrigger/offset,MaxSpreadPrice,HISTspread,slippage); không có input giá tuyệt đối “gần cản” khác. Không scale ATR/RR/bars/score/%/commission/tiền tài khoản. Chờ/exclude nếu thiếu D1; không dùng forming/future close.
- Sửa shared helper/callers/Inputs/preset,indicator+EA+adapter0/0. Risk/Execution/Zones nguyênhash, không thay MinRR hoặc thử hệ số/preset khác. Full source/binary/sets trong patch/ và can_ho_tro_v4.
- Prefix M1 seed20261101:200/200 mode0 +200/200 mode1;17 scale unit checks/0 failures. HIST default mode1 toàn fixture:459 signals,1519 checks/0 failures. D1 fixture từ closed H1 previous calendar day, production D1 thật.
- M3b EXIT_1R Model4,XAUUSD M5,01/07–31/10/2026,6296,MetaQuotes-Demo,100000USD,InpRiskPercent0.5:44.373.721 ticks,100% real,29 signals/29 closed. Indicatorcallback adapter cùng kỳ29/29,31 cột,0 mismatch;nonvisual,không tuyên bốvisual QA.
- EXIT_1R win37.931034%;gross/net R theo cash relation deal−0.166947352/−0.169998866;PF_R0.746696517;netUSD−26743.06;equityDD43201.44USD/40.06%;SL17,TP11,TIMEOUT1. Commission0,fee0,swap−438.97 từ deal;entry quote spread0.14–0.64,mean0.315172414. Không scale actual quote/fees; commission7 input không override broker.
- HIST459/459 mỗi rule: EXIT win43.790850%,gross/net−0.025948576/−0.130061607R,PF.752869416;TRAIL win43.355120%,gross/net−0.032347739/−0.136460770R,PF.741521351. Hết dữ liệu23/10/2026;không bịa phần01–09/2021 hay24–31/10/2026. Source profile default mới không đồng nhất profile RR/reference=false cũ1393 nên không gán toàn thay đổi cho scale.

## Bằng chứng (đường dẫn + SHA-256)
{proof}

```text
{chr(10).join(compile_quotes)}
V401_SCALE_UNITS 17/17
V401_HIST_DONE signals=459 failures=0
PREFIX totals: mode0=200/200 mode1=200/200
POSITIVE_PARITY: EA29 indicator29 matched29 columns31 mismatches0
```
CSV/reportHTML/INI/SET/log gốc trong v401_tp1r/,v401_trail/,v401_indicator/,native_hist/outputs/;prefix kết quả từng case ở prefix_r2_worker_*/mode*/;nguồn/runner trong validation_sources/. Manifest loại executable/runtime portable,hash tất cả file bằng chứng được giao,0 mismatch. ZIP M3a giữ nguyên f515b8565e8b63cb64c27b8b12dea6e4457ec0d4190dd9fa330d17e6c32cdbf6.

## Lệch so với kế hoạch và lý do
1. **TRAIL chưa chạy hết kỳ:** lệnh đầu09/07 19:05 SELL6.34 @4125.79 SL4133.67 khớp; redundant modify cùng SL/TP0 trả Invalid stops,EA TesterStop. Chỉ4.055.862 ticks/1 forced close−145.82USD;exit_reason raw trống,không dùng làm baseline. Đây là lỗi execution đã tồn tại,không tự sửa ngoài “không thay đổi gì khác”.
2. **Risk tiền broker chưa đúng0.5%:**29 gross deals khớp (exit−entry)*side*volume*100,max lỗi4.72e−10USD. Initial risk theo relation deal đúng10 lần risk_USD ledger;ví dụ4995.92USD so ledger499.592. Sizing thực khoảng5% mặc dù input0.5%. Raw meanR ledger−1.66947/−1.69999 bị phóng đại10x; chỉ dùng R tính lại đã nêu và giao29 dòng đối soát. Chưa sửa Risk sang OrderCalcProfit hoặc rerun sizing khác vì ngoài scope. DD40.06% là kết quả run này,không chia10 để dự đoán0.5%.
Hai blocker đã báo sớm codex_007_v401_blocker.md;phần độc lập đều hoàn tất. Checkpoint đó được báo cáo này thay thế. Không có chỉ thị mới mở sửa hai phần khi chốt.

## Việc chưa xong / rủi ro đã biết
TRAIL hết kỳ và B0v4.0.1 đúng risk0.5% chưa đạt;release chưa sẵn sàng thay ZIP. Parity là positive callbackadapter,không visual tester. HIST là OHLC/closed-H1-derived D1 fixture,không phải tick thật cả2021–2026. Commission broker hiện quan sát0,không coi là kiểm cấu hình fee mong muốn. Các giới hạn M3a/M3b khác còn như hướng dẫn.

## Câu hỏi cho Claude/người dùng
Claude cần quyết định riêng về bỏ modify không đổi SL/TP và dùng OrderCalcProfit kiểm/định lượng risk,như checkpoint blocker. Codex chưa tự mở scope đó hoặc tối ưu tham số.

## Bước tiếp theo đề xuất
DỪNG theo yêu cầu;chờ Claude nghiệm thu v4.0.1 và chỉ thị về blockers. Không thay ZIP phát hành,không M4/M5,không bật heartbeat.
"""
p=ROOT/'codex_outbox/codex_007_v401.md';assert not p.exists();p.write_text(out,encoding='utf-8')
print(json.dumps(dict(report=p.relative_to(ROOT).as_posix(),files=len(files),hash_mismatches=0,prefix={'mode0':200,'mode1':200},M3b_complete=False,release_zip_unchanged=True)))
