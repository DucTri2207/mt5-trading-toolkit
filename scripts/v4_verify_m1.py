"""Verify the delivered M1 evidence and build provenance without a detector."""
from pathlib import Path
import csv,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"reports/can_ho_tro_v4/20261101_m1_v2"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rd(p):return list(csv.DictReader(p.open(encoding="utf-8-sig",newline="")))
def main():
    checks=[]
    def check(name,ok,actual):checks.append(dict(name=name,passed=bool(ok),actual=actual))
    counts=json.loads((RUN/"M1_COUNTS.json").read_text());core=counts["core"]
    check("core_native_checks",core["failures"]==0,core)
    check("candidate_accounting",counts["candidates"]==core["candidates"]==core["published"]+core["blocked"],counts["statuses"])
    check("published_csv",core["published"]==len(rd(RUN/"portable_terminal/MQL5/Files/v4_fixture/v4_stream.csv")),core["published"])
    check("guard_reject_accounting",counts["guard_rejected"]==core["guard_rejected"],counts["guard_rejected"])
    check("F1_legacy_witnesses",counts["f1_witnesses"]>=3,counts["f1_witnesses"])
    for mode,p in counts["parity"].items():check("compat_event_parity_"+mode,p["mismatches"]==0,p)
    check("diff_native_reason_for_every_row",counts["diff_requiring_event_trace"]==0,counts["diff_requiring_event_trace"])
    prefixes=rd(RUN/"PREFIX_200.csv")
    check("prefix_200_independent_cases",len(prefixes)==200 and len({x["case"] for x in prefixes})==200 and len({x["visible_m5"] for x in prefixes})==200 and all(x["matched"]=="PASS" for x in prefixes),len(prefixes))
    include=ROOT/"can_ho_tro_v4/MQL5/Include/CanHoTroV4"
    for i in range(4):
        p=RUN/f"prefix_worker_{i}/build_inputs/TestV4Acceptance_final_200/SHA256.json"
        hashes={k.replace("\\","/"):v for k,v in json.loads(p.read_text()).items()}
        bad=[f.name for f in include.glob("*.mqh") if hashes.get("CanHoTroV4/"+f.name)!=sha(f)]
        check(f"prefix_worker_{i}_current_include_hashes",not bad,bad)
    details=json.loads((RUN/"lifecycle_run/portable_terminal/MQL5/Files/v4_fixture/details_result.json").read_text())
    check("F3_F4_native_details",details["failures"]==0 and details["real_zone_matches"]>0 and details["collisions"]==0 and details["rr_modes"]==3,details)
    geometry=rd(RUN/"portable_terminal/MQL5/Files/v4_fixture/source_geometry_100.csv")
    check("F6_100_unique_drawn_sources",len(geometry)==100 and len({x["signal_id"] for x in geometry})==100 and all(x["matched"]=="PASS" for x in geometry),len(geometry))
    lifecycle=json.loads((RUN/"portable_terminal/MQL5/Files/v4_fixture/lifecycle_result.json").read_text())
    check("F7_reload_and_simulated_disconnect",lifecycle["failures"]==0,lifecycle)
    ui=rd(RUN/"lifecycle_run/portable_terminal/MQL5/Files/v4_fixture/indicator_lifecycle_r5.csv")
    check("F7_real_indicator_M5_M15_M5",[x["chart_period"] for x in ui]==["5","15","5"] and all(x["actual_indicator_arrow_geometry"]=="PASS" for x in ui),ui)
    build=json.loads((RUN/"lifecycle_run/BUILD_M1_deferred_writer.json").read_text())
    check("indicator_compile_0_0",build["passed"] and build["errors"]==0 and build["warnings"]==0,dict(errors=build["errors"],warnings=build["warnings"]))
    check("delivered_binary_is_UI_tested_binary",sha(ROOT/"can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5")==build["binary_sha256"],build["binary_sha256"])
    check("delivered_main_source_is_compiled_source",sha(ROOT/"can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5")==build["source_sha256"],build["source_sha256"])
    check("protected_v301_source_unchanged",sha(ROOT/"duc_tri_can_ho_tro.mq5")=="5a244553a7e659fb50c78481294531e38b9e60d1d1c0b11adbc26db7c7226405",sha(ROOT/"duc_tri_can_ho_tro.mq5"))
    output=dict(checks=len(checks),failures=sum(not x["passed"] for x in checks),results=checks)
    (RUN/"FINAL_CHECKS.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps(dict(checks=output["checks"],failures=output["failures"])))
    for c in checks:
        if not c["passed"]:print(c["name"],c["actual"])
    if output["failures"]:raise SystemExit(1)
if __name__=="__main__":main()
