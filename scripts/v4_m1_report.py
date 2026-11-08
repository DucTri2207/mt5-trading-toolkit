"""Summarize native MT5 CSV evidence. Does not implement a detector."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import csv, json, argparse

def load(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write(path, rows, fields):
    with path.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument("--run",required=True);a=p.parse_args()
    run=Path(a.run);data=run/"portable_terminal/MQL5/Files/v4_fixture"
    compat=load(data/"compat_stream.csv");v4=load(data/"v4_stream.csv")
    candidates=load(data/"v4_candidates.csv");guards=load(data/"guard_rejects.csv")
    core=json.loads((data/"core_result.json").read_text())
    trace_root=run/"NATIVE_TRACE"
    trace=load(trace_root/"compat_zone_trace.csv")
    traced={(x["confirm_bar_open"],x["direction"],x["zone_start"],round(float(x["distal"]),8),round(float(x["proximal"]),8)):x for x in trace}
    sweep_path=trace_root/"compat_sweep_trace.csv"
    sweeps={(x["observation_time"],x["stable_zone_id"]):x for x in load(sweep_path)} if sweep_path.exists() else {}
    rr_path=trace_root/"compat_rr_rejections.csv"
    rr={(x["confirm_bar_open"],x["stable_zone_id"]) for x in load(rr_path) if x["epsilon_allows"]=="true"} if rr_path.exists() else set()
    plan_path=trace_root/"compat_plan_trace.csv"
    plan={x["observation_time"]:x for x in load(plan_path)} if plan_path.exists() else {}
    candidate_map={}
    guard_map={}
    for c in candidates:candidate_map.setdefault((c["confirm_bar_open"],c["source_zone_id"]),[]).append(c["status"])
    for c in guards:guard_map.setdefault((c["confirm_bar_open"],c["source_zone_id"]),[]).append(c["status"])
    parity={}
    for mode in ("stream","idle"):
        x=load(data/f"compat_{mode}.csv"); y=load(data/f"oracle_{mode}.csv")
        columns=list(y[0]); mismatches=[]
        for i,(left,right) in enumerate(zip(x,y)):
            changed=[k for k in columns if left[k]!=right[k]]
            if changed:mismatches.append(dict(index=i,columns=changed))
        parity[mode]=dict(compat=len(x),oracle=len(y),compared_columns=columns,
            mismatches=len(mismatches)+abs(len(x)-len(y)),first_mismatch=mismatches[:1])
    write(run/"F1_GUARD_REJECTS.csv",guards,list(guards[0]) if guards else ["signal_id"])
    published={(r["confirm_bar_open"],r["direction"],r["source_zone_id"],r["sweep_time"]) for r in v4}
    witnesses=[dict(signal_id=g["signal_id"],source_zone_id=g["source_zone_id"],
        confirm_bar_open=g["confirm_bar_open"],signal_known_time=g["signal_known_time"],
        zone_known_time=g["zone_known_time"],sweep_bar_open=g["sweep_bar_open"],
        before="SHADOW_PRE_GUARD_CANDIDATE",after="REJECTED",reason=g["status"])
        for g in guards if (g["confirm_bar_open"],"1" if g["is_buy"]=="1" else "-1",g["source_zone_id"],g["sweep_bar_open"]) not in published]
    write(run/"F1_SHADOW_WITNESSES.csv",witnesses,list(witnesses[0]) if witnesses else ["signal_id"])
    legacy_guard_keys={(x["confirm_bar_open"],x["stable_zone_id"]) for x in trace}
    causal_events={(x["confirm_bar_open"],x["source_zone_id"]) for x in v4}
    witnesses=[dict(w,compat_published=True) for w in witnesses if (w["confirm_bar_open"],w["source_zone_id"]) in legacy_guard_keys and (w["confirm_bar_open"],w["source_zone_id"]) not in causal_events]
    write(run/"F1_WITNESSES.csv",witnesses,list(witnesses[0]) if witnesses else ["signal_id"])
    # Canonical geometry matches regions independently of sequential/hash IDs.
    def key(r):
        return (r["confirm_bar_open"],r["direction"],r["zone_start"],round(float(r["distal"]),8),round(float(r["proximal"]),8))
    old={key(r):r for r in compat};new={key(r):r for r in v4}
    guardtimes={g["confirm_bar_open"] for g in guards}
    blockedtimes={g["confirm_bar_open"] for g in candidates if g["status"]!="PUBLISHED"}
    diffs=[]
    for k in sorted(old.keys()|new.keys()):
        x=old.get(k);y=new.get(k);why=[]
        if x and y:
            columns=[c for c in ("source_zone_id","entry","sl","tp1","tp2","publish_time") if x[c]!=y[c]]
            if not columns:continue
            if "source_zone_id" in columns:why.append("F3_STABLE_HASH_ID")
            if any(c in columns for c in ("entry","sl","tp1","tp2")):
                why.append("F1_ALTERNATIVE_ELIGIBLE_SWEEP" if guard_map.get((y["confirm_bar_open"],y["source_zone_id"])) else "UNRESOLVED_NATIVE_TRACE_REQUIRED")
        else:
            columns=["publication"]
            if x:
                z=traced[k];event=(x["confirm_bar_open"],z["stable_zone_id"])
                if int(z["time_invalid"])>0 and int(z["time_invalid"])<=int(x["publish_time"]):why.append("F2_FLIP_INVALID_AT_OBSERVATION")
                why.extend(guard_map.get(event,[]))
                why.extend("F5_"+s for s in candidate_map.get(event,[]) if s!="PUBLISHED")
            else:
                if (y["confirm_bar_open"],y["source_zone_id"]) in rr:why.append("F4_LITERAL_RR_REJECT_EPSILON_ALLOWS")
                sweep=sweeps.get((y["publish_time"],y["source_zone_id"]),{})
                if sweep.get("sweep_before_known")=="true":why.append("F1_NEW_CONFIRM_AFTER_EARLY_SWEEP_REMOVED")
                prior=plan.get(y["publish_time"],{})
                if prior.get("active_before_detect")=="true":why.append("F5_COMPAT_DISPLAY_PLAN_ACTIVE")
                if prior.get("compat_publication_on_bar")=="true":why.append("F5_COMPAT_FIRST_ZONE_BREAK")
            if not why:why.append("UNRESOLVED_NATIVE_TRACE_REQUIRED")
        diffs.append(dict(confirm_bar_open=k[0],direction=k[1],zone_start=k[2],distal=k[3],proximal=k[4],
            compat_present=bool(x),v4_present=bool(y),compat_zone_id=x["source_zone_id"] if x else "",
            v4_zone_id=y["source_zone_id"] if y else "",changed="|".join(columns),reason="|".join(why),
            attribution="EXACT_ID_CHANGE" if x and y and columns==["source_zone_id"] else ("NATIVE_STAGE_EVIDENCE" if "UNRESOLVED_NATIVE_TRACE_REQUIRED" not in why else "REQUIRES_EVENT_TRACE")))
    write(run/"DIFF_V301_V4.csv",diffs,list(diffs[0]))
    counts=Counter(r["status"] for r in candidates)
    years={}
    for c in candidates:
        year=datetime.fromtimestamp(int(c["signal_known_time"]),timezone.utc).year
        years.setdefault(year,Counter())[c["status"]]+=1
    result=dict(core=core,parity=parity,candidates=len(candidates),statuses=dict(counts),
        guard_rejected=len(guards),guard_shadow_denominator=core.get("guard_candidates"),
        guard_rejected_ratio=(len(guards)/core["guard_candidates"] if core.get("guard_candidates") else None),
        guard_relative_to_actual_candidates=len(guards)/len(candidates),
        f1_witnesses=len(witnesses),diff_rows=len(diffs),diff_requiring_event_trace=sum(d["attribution"]=="REQUIRES_EVENT_TRACE" for d in diffs),
        years={str(k):dict(v) for k,v in years.items()},
        scope="retrospective, closed-prefix native MQL5 replay, synthetic opening bid/ask spread 0.20; not tick execution")
    (run/"M1_COUNTS.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("candidates","statuses","guard_rejected","guard_shadow_denominator","f1_witnesses","diff_rows","diff_requiring_event_trace")}))
if __name__=="__main__":main()
