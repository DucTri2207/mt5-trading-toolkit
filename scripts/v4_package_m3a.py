# -*- coding: utf-8 -*-
"""Package only completed native M3a evidence; never launches a tester."""
import hashlib,json,shutil,zipfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1'
RELEASE=ROOT/'can_ho_tro_v4'
F=RUN/'portable_terminal/MQL5/Files/v4_fixture'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def record(p,base):return dict(path=p.relative_to(base).as_posix(),bytes=p.stat().st_size,sha256=sha(p))
summary=json.loads((RUN/'M3A_TEST_SUMMARY.json').read_text())
assert summary['parity']['matched']==summary['parity']['ea']>0 and summary['journal']['failures']==0
build=json.loads((RUN/'BUILD_r3.json').read_text())
for kind,name in [('ea','Experts/CanHoTroV4_TesterEA'),('indicator','Indicators/duc_tri_can_ho_tro_v4')]:
    assert sha(RELEASE/f'MQL5/{name}.mq5')==build[kind]['source_sha256']
    assert sha(RELEASE/f'MQL5/{name}.ex5')==build[kind]['binary_sha256']
original=ROOT/'duc_tri_can_ho_tro.mq5'
m1=json.loads((ROOT/'reports/can_ho_tro_v4/20261101_m1_v2/MANIFEST.json').read_text(encoding='utf-8'))
expected=next(x['sha256'] for x in m1['files'] if x['path']=='duc_tri_can_ho_tro.mq5')
assert sha(original)==expected
presets=RELEASE/'Presets';presets.mkdir(exist_ok=True)
for kind in ['ea','indicator']:shutil.copy2(F/f'{kind}_default.set',presets/f'{kind}_default.set')
write(RELEASE/'MANIFEST.json',dict(version='4.0',scope='M3a release; M3b pending',files=[record(p,RELEASE) for p in sorted(RELEASE.rglob('*')) if p.is_file() and p.name!='MANIFEST.json']))
stage=RUN/'release_stage';stage.mkdir(exist_ok=False)
target=stage/'can_ho_tro_v4';shutil.copytree(RELEASE,target)
validation=target/'validation';validation.mkdir()
for name in ['PROTOCOL.json','BUILD_r3.json','NATIVE_PARITY.json','M3A_TEST_SUMMARY.json']:
    shutil.copy2(RUN/name,validation/name)
for p in RUN.glob('COMPILE_*_r3.log'):shutil.copy2(p,validation/p.name)
for p in RUN.glob('EXIT_*_r3.json'):shutil.copy2(p,validation/p.name)
for p in RUN.glob('NATIVE_*_r3.ini'):shutil.copy2(p,validation/p.name)
for p in F.iterdir():
    if p.suffix in ['.json','.csv','.set']:shutil.copy2(p,validation/p.name)
shutil.copy2(RUN/'portable_terminal/MQL5/Files/V4_TESTER_OUTSIDE_REJECTED.txt',validation/'V4_TESTER_OUTSIDE_REJECTED.txt')
shutil.copytree(RUN/'build_inputs_r3/tests',validation/'native_sources',ignore=shutil.ignore_patterns('*.ex5'))
scripts=validation/'scripts';scripts.mkdir()
for name in ['v4_m3a.py','v4_package_m3a.py','v4_native_m1.py','v4_build_m1.py','v4_port_m1.py']:
    shutil.copy2(ROOT/'scripts'/name,scripts/name)
for run_id,names in [('20261101_m1_v2',['DIFF_V301_V4.csv','REVERSAL_CAUSAL_FIXTURE.set','REVERSAL_COMPAT_FIXTURE.set','REPORT_M1.md']),('20261101_m2_v1',['SCORECARD_HIST_SUMMARY.json','SIGNAL_CHANGE_DISJOINT.csv','NORMAL_ZONE_EXPOSURE.json','LEGACY_PARITY.json','REPORT_M2.md'])]:
    d=validation/run_id;d.mkdir()
    for name in names:shutil.copy2(ROOT/'reports/can_ho_tro_v4'/run_id/name,d/name)
report=f"""# M3a — ĐẠT; v4.0 đóng gói, M3b chờ người dùng

Native parity production frontends: {summary['parity']['matched']}/{summary['parity']['ea']} sự kiện, {summary['parity']['columns']} cột, 0 khác biệt. Guard EA ngoài tester INIT_FAILED; không gửi lệnh. Journal tổng hợp: {summary['journal']['checks']} checks / 0 failures; 9 deal, 4 position, initial SL/modified SL/partials/commission/swap/fee/labels/net R. Ledger EA 31 cột, serializer fixture net492 / .984R, thứ tự thời gian PASS. Cả 5 build cuối 0 errors, 0 warnings.

Dùng terminal portable riêng, build 6283; native script OnStart, không Strategy Tester/visual tester, không login/account copy. Indicator và EA gọi chung V4ObserveClosedBar; guard được gọi qua OnInit thực được rename trong wrapper. Fixture chỉ bơm giá/ATR/thời gian, không chạy CTrade hoặc OnTick account branch. Không tuyên bố parity execution/P&L broker.

Shared LogicHelpers/Observation tách thân hàm từ indicator; detector/Zones/Signals và default không chỉnh để cứu kết quả. Native1393 khớp số M2. Tắt notification khi EA/fixture. Phiên bị ngắt trước đó chỉ có probe; giữ nguyên mọi run cũ. Build r1 và runtime r2 lỗi fixture đã giữ tại workspace; gate cuối r3, không dùng lỗi cũ làm PASS. Warm-up thiếu zone là chờ dữ liệu, fixture r3 chỉ fail khi I/O lỗi; thêm guard tránh index lịch sử rỗng.

M2 đã được Claude006 nghiệm thu có giới hạn; fixture tổng hợp bổ sung thay cổng broker22. Dữ liệu journal tổng hợp đi qua production accumulator; không mock HistorySelect/order API. Chưa có lịch sử broker thật. HIST âm và MaxTests vùng thường được ghi nguyên trong CHANGELOG. M3b chờ demo do người dùng tự login; M4/M5 không thực hiện.

Original v3.01 SHA-256: {expected}; khớp manifest M1. Release binary hash được đối chiếu BUILD_r3.json. MANIFEST nội bộ hash source/docs/presets; MANIFEST ngoài hash toàn payload và ZIP (tránh tự tham chiếu hash ZIP). ZIP_VERIFICATION.json bên ngoài ghi kết quả giải nén/hash. Không chứa terminal/account/credentials.

Tái lập: scripts/v4_m3a.py, RUN mới, prepare/build --label mới/run tuần tự NativeM3a_ea, NativeM3a_indicator, TestV4M3aJournal/analyze. Cần fixture H1/M5 và terminal/compiler MT5/standard include riêng. validation/native_sources lưu wrapper/adapters và test thực; validation có output gốc + config native. M3b chưa có config broker hợp lệ; không đưa thông số đăng nhập giả hay chạy tester.
"""
(RUN/'REPORT.md').write_text(report,encoding='utf-8');(validation/'REPORT.md').write_text(report,encoding='utf-8')
payload=[record(p,stage) for p in sorted(stage.rglob('*')) if p.is_file()]
archive=RUN/'CanHoTro_v4.0_M3a.zip'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for x in payload:z.write(stage/x['path'],x['path'])
write(RUN/'MANIFEST.json',dict(version='4.0',created=datetime.now(timezone(timedelta(hours=7))).isoformat(),scope='M3a only; M3b pending',zip=record(archive,RUN),files=payload,original_v301_sha256=expected))
verify=RUN/'extracted_verification';verify.mkdir(exist_ok=False)
with zipfile.ZipFile(archive) as z:
    for name in z.namelist():
        resolved=(verify/name).resolve();assert verify.resolve() in resolved.parents
    z.extractall(verify)
actual={p.relative_to(verify).as_posix():record(p,verify) for p in verify.rglob('*') if p.is_file()}
errors=[x['path'] for x in payload if actual.get(x['path'])!=x]
assert len(actual)==len(payload) and not errors
write(RUN/'ZIP_VERIFICATION.json',dict(passed=True,files=len(payload),mismatches=errors,zip_sha256=sha(archive),uncompressed_bytes=sum(x['bytes'] for x in payload)))
print(json.dumps(dict(files=len(payload),zip_bytes=archive.stat().st_size,zip_sha256=sha(archive),mismatches=0,original_unchanged=True)))
