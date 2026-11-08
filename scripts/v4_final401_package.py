# -*- coding: utf-8 -*-
"""Package the fixed scope only; assert all final gates before creating a new ZIP."""
import json,hashlib,shutil,zipfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/can_ho_tro_v4/20261102_v401_final_v1'
REL=ROOT/'can_ho_tro_v4'
OLD=ROOT/'reports/can_ho_tro_v4/20261102_v401_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    assert load(RUN/'units/risk_stops_result.json')=={'checks':25,'failures':0}
    for mode in [0,1]:assert load(RUN/f'prefix_smoke/mode{mode}/prefix_result.json')['prefix_passed']==20
    assert load(RUN/'RISK_EXECUTION_AUDIT.json')['passed'] and load(RUN/'POSITIVE_PARITY.json')['matched']==29
    for name in ['BUILD_v401.json','BUILD_indicator.json','BUILD_indicator_adapter.json']:
        b=load(RUN/'build_r2'/name);assert b['passed'] and b['errors']==b['warnings']==0
    for name,build in [('MQL5/Experts/CanHoTroV4_TesterEA.ex5','BUILD_v401.json'),('MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5','BUILD_indicator.json')]:
        assert sha(REL/name)==load(RUN/'build_r2'/build)['binary_sha256']
    oldzip=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/CanHoTro_v4.0_M3a.zip'
    assert sha(oldzip)=='f515b8565e8b63cb64c27b8b12dea6e4457ec0d4190dd9fa330d17e6c32cdbf6'
    val=REL/'validation';val.mkdir(exist_ok=False)
    for name in ['REPORT.md','RESULTS_FINAL.json','RISK_EXECUTION_AUDIT.json','SCOPE_DIFF.json','SCOPE_LOCK.json','POSITIVE_PARITY.json','RISK_WARNINGS.filtered.txt']:
        shutil.copy2(RUN/name,val/name)
    for name in ['final401_tp1r','final401_trail']:shutil.copytree(RUN/name,val/name)
    for name in ['build_r2','units','prefix_smoke']:
        dst=val/name;dst.mkdir()
        for p in (RUN/name).iterdir():
            if p.is_file():shutil.copy2(p,dst/p.name)
        if name=='prefix_smoke':
            for mode in ['mode0','mode1']:shutil.copytree(RUN/name/mode,dst/mode)
    shutil.copytree(OLD/'native_hist/outputs',val/'accepted_hist')
    for name in ['PREFIX_401_SUMMARY.json','FROZEN_INPUTS.json','LOCK_V401.json']:shutil.copy2(OLD/name,val/name)
    shutil.copy2(ROOT/'reports/can_ho_tro_v4/20261101_m1_v2/DIFF_V301_V4.csv',val/'DIFF_V301_V4.csv')
    source=val/'sources';source.mkdir()
    for name in ['v4_final401_checks.py','v4_final401_audit.py','v4_final401_package.py','v4_m3b.py','v4_v401.py','v4_build_m1.py']:shutil.copy2(ROOT/'scripts'/name,source/name)
    for name in ['TestV401RiskStops.mq5','TestV4Core.mq5','TestV4Acceptance.mq5','FixtureData.mqh']:shutil.copy2(ROOT/'tests/v4'/name,source/name)
    for name in ['PlanStateV301.mqh','KillzoneV301.mqh']:shutil.copy2(RUN/'prefix_smoke/portable_terminal/MQL5/Scripts/V4'/name,source/name)
    unchanged=[]
    for p in (REL/'MQL5').rglob('*'):
        if p.is_file() and p.suffix!='.ex5':
            old=OLD/'patch'/p.relative_to(REL)
            if old.exists() and sha(p)==sha(old):unchanged.append(dict(path=p.relative_to(REL).as_posix(),sha256=sha(p)))
    assert any(x['path'].endswith('/Signals.mqh') for x in unchanged)
    assert any(x['path'].endswith('/PriceScale.mqh') for x in unchanged)
    dump(val/'UNCHANGED_SOURCE_HASHES.json',unchanged)
    payload=[dict(path=p.relative_to(REL).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(REL.rglob('*')) if p.is_file() and p!=REL/'MANIFEST.json']
    dump(REL/'MANIFEST.json',dict(version='4.0.1',status='tests passed; awaiting independent Claude acceptance',v40_M3a_release_prohibited=True,files=payload))
    zipath=RUN/'CanHoTro_v4.0.1.zip';assert not zipath.exists()
    with zipfile.ZipFile(zipath,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(REL.rglob('*')):
            if p.is_file():z.write(p,'can_ho_tro_v4/'+p.relative_to(REL).as_posix())
    extracted=RUN/'extracted_verification';extracted.mkdir()
    with zipfile.ZipFile(zipath) as z:
        assert z.testzip() is None
        assert all(not Path(x).is_absolute() and '..' not in Path(x).parts for x in z.namelist());z.extractall(extracted)
    target=extracted/'can_ho_tro_v4';files=[p for p in REL.rglob('*') if p.is_file()]
    mismatches=[p.relative_to(REL).as_posix() for p in files if sha(p)!=sha(target/p.relative_to(REL))];assert not mismatches
    assert len(files)==len([p for p in target.rglob('*') if p.is_file()])
    for x in payload:assert sha(target/x['path'])==x['sha256']
    dump(RUN/'ZIP_VERIFICATION.json',dict(passed=True,zip_sha256=sha(zipath),files=len(files),payload_files=len(payload),mismatches=[],zip_crc_passed=True,old_M3a_unchanged_sha256=sha(oldzip)))
    manifestfiles=[dict(path=p.relative_to(RUN).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(RUN.rglob('*')) if p.is_file() and 'portable_terminal' not in p.parts and 'extracted_verification' not in p.parts and p.name not in ['MANIFEST.json','MANIFEST_VERIFICATION.json']]
    dump(RUN/'MANIFEST.json',dict(version='4.0.1',zip=dict(path=zipath.name,bytes=zipath.stat().st_size,sha256=sha(zipath)),files=manifestfiles))
    assert all(sha(RUN/x['path'])==x['sha256'] for x in manifestfiles)
    dump(RUN/'MANIFEST_VERIFICATION.json',dict(passed=True,files=len(manifestfiles),mismatches=[]))
    proof='\n'.join('- `'+(RUN/n).relative_to(ROOT).as_posix()+'` — SHA-256 `'+sha(RUN/n)+'`' for n in ['CanHoTro_v4.0.1.zip','REPORT.md','RESULTS_FINAL.json','RISK_EXECUTION_AUDIT.json','MANIFEST.json','ZIP_VERIFICATION.json','MANIFEST_VERIFICATION.json'])
    out='''# codex_008 — v4.0.1 final — ĐẠT kiểm thử trong phạm vi; chờ Claude nghiệm thu
Đã đọc README_QUY_UOC, claude_003, claude_011; kế thừa hồ sơ tại file, không đọc chat cũ.
Thời điểm: '''+datetime.now(timezone(timedelta(hours=7))).isoformat()+'''

## Đã làm

- Sửa OrderCalcProfit làm nguồn chính risk/lot/cost/panel/EA; mismatch tick>1% cảnh báo đúng câu, oracle lỗi fail closed. Giữ detector/scale/RR/preset.
- Bỏ no-op modify sau chuẩn hóa; stops/freeze defer giữ SL, lỗi khác fail closed. Đồng bộ stop ảo/thực.
- EA/indicator/adapter cuối0 lỗi0 cảnh báo; risk/stop25/25, prefix smoke20/20 mỗi mode. Tái sử dụng nghiệm thu prefix200×2,HIST459; EA signal mới29/29 khớp31 cột indicator đã nghiệm thu.
- Tick thật đủ kỳ01/07–31/10/2026 end exclusive: mỗi rule44.373.721 tick/100% real,29 closed.58/58 lệnh đạt risk0.5% trong1 bước lot; không FAIL_CLOSED. Lệnh đầu0.63lot,risk496.44USD/target500 thay sizing cũ6.34lot.
- EXIT_1R:win37.931034%,mean gross−.1669473524R,net−.1699986735R,PF_R.7466967436,net−2482.66USD,equityDD4847.79USD/4.79%,swap−43.80USD. Exit SL17/TP11/TIMEOUT1.
- TRAIL:win37.931034%,mean gross−.0678778874R,net−.0711303713R,PF_R.8940135144,net−1113.86USD,equityDD5324.20USD/5.19%,swap−47.12USD. Bỏ51.566 no-op modify; hết kỳ. Commission/fee0 cả hai theo deal, không tự đặt phí broker.
- HIST giữ kết quả459 signals mỗi rule:mean net EXIT−.1300616069R/TRAIL−.1364607699R; không chạy lại toàn kỳ trong scope sửa lot/trail này. Cả HIST/tick đều âm, chưa có bằng chứng lợi thế.
- Đóng gói v4.0.1 source/binary/preset/docs/validation,manifest+ZIP,giải nén kiểm mọi hash. **v4.0 M3a KHÔNG được phát hành vì lỗi lot ×10**; hash ZIP cũ giữ nguyên.

## Bằng chứng (đường dẫn + SHA-256)

'''+proof+'''

### Output thật cuối

- EA: `Result: 0 errors, 0 warnings, 1670 ms elapsed, cpu='X64 Regular'`.
- Indicator: `Result: 0 errors, 0 warnings, 2681 ms elapsed, cpu='X64 Regular'`.
- Adapter: `Result: 0 errors, 0 warnings, 2335 ms elapsed, cpu='X64 Regular'`.
- Native risk_stops_result: `{"checks":25,"failures":0}`.
- Prefix từng mode: `prefix_passed=20,prefix_total=20`; log và unit_checks.csv kèm theo.
- ZIP_VERIFICATION.json: passed=true, mọi file sau giải nén cùng hash payload/source, CRC đạt.

## Lệch / giới hạn

Không blocker còn mở của claude_011. Reuse full-prefix/HIST/indicator được giải thích và có hash trong REPORT.md; mới chạy lại smoke prefix,focused units và hai EA tick thật. Không chạy visual/forward/M4/M5. Nhánh stop/freeze kiểm pure unit; run broker này không gặp deferred/rejected stops. Chưa kiểm partial fill,journal broker,FX lịch sử,DST,Telegram/push/crash recovery. Risk tại SL chưa gồm gap/phí. Báo cáo đầy đủ và ledger cho Claude audit độc lập.

## Điểm dừng

Đã đóng gói, ghi báo cáo; DỪNG chờ Claude nghiệm thu. Không bật heartbeat hoặc mở mốc khác.
'''
    (ROOT/'codex_outbox/codex_008_v401_final.md').write_text(out,encoding='utf-8')
    print(json.dumps(dict(zip=zipath.name,sha256=sha(zipath),files=len(files),verified=True),ensure_ascii=True))
if __name__=='__main__':main()
