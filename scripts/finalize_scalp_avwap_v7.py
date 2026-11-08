# -*- coding: utf-8 -*-
"""Preserve AVWAP tests and one declared zero-friction diagnostic."""
import csv
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_avwap_v7 as v


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    w = v.w; run = v.RUN; lock = read(run/'EXPERIMENT_LOCK.json')
    assert read(run/'PREFIX_CHECKS.json')['passed']
    verification = read(run/'VERIFICATION.json')
    assert not verification['qualified'] and all(verification['fresh_unchanged'].values())
    control_lock = dict(hypothesis='SWING_AVWAP already counted in87',
        costs=dict(id='ZERO',spread=0.,slip=0.,commission_price=0.),
        purpose='one diagnostic of signal vs execution friction;not a broker-feasible candidate or new strategy',
        main_lock_sha256=sha(run/'EXPERIMENT_LOCK.json'),new_scenarios=1,
        frozen_before_control_results=True)
    control_path = run/'ZERO_FRICTION_LOCK.json'
    if control_path.exists():
        assert read(control_path)==control_lock
    else:
        write_json(control_path,control_lock)
    w.FAMILIES.update(v.NAMES)
    parts = [np.load(run/(name+'_candidates.npz'))['raw'] for name in v.NAMES.values()]
    raw = w.add_fresh(np.concatenate(parts)); source = np.load(w.BASE/'rates.npz'); market = bars_matrix(source['m1'])
    result_path = run/'ZERO_FRICTION_CONTROL.json'
    if result_path.exists():
        control = read(result_path)
    else:
        spec = next(s for s in v.SPECS if s['name']=='SWING_AVWAP')
        trades,rejections = v.run_serial(raw,market,spec,control_lock['costs'])
        control = dict(name=spec['name'],cost='ZERO',metrics=w.summarize(trades,market,lock),
                       rejections=rejections,not_deployable=True)
        write_json(run/'SWING_AVWAP_ZERO_trades.json',dict(trades=trades,rejections=rejections))
        write_json(result_path,control)
    rows = read(run/'summary.json')['rows']+[control]; flat = []
    for row in rows:
        m = row['metrics']; freq = m['frequency']
        flat.append(dict(name=row['name'],cost=row['cost'],n=m['n'],win_rate=m['win_rate'],pf=m['pf'],net_r=m['total_r'],
                         expectancy=m['expectancy'],mean_week=freq['mean'],empty_weeks=len(freq['empty_weeks']),
                         weeks_5_to_10=freq['weeks_with_5_to_10'],frequency_pass=m['frequency_pass'],
                         economic_screen_pass=m['economic_screen_pass'],adjusted_lower=m['expectancy_month_bootstrap_lower_family95']))
    with (run/'ALL_V7_EXPERIMENTS.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    previous=w.ROOT/'reports/can_ho_tro_scalp/20261101_failed_reclaim_v6/CUMULATIVE_REGISTRY.json'
    assert read(previous)['cumulative']==dict(hypotheses=82,scenarios=318)
    write_json(run/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=82,scenarios=318,sha256=sha(previous)),
        new=dict(hypotheses=5,cost_scenarios=15,diagnostic_zero_friction_scenarios=1,total_scenarios=16),
        cumulative=dict(hypotheses=87,scenarios=334),tests=116,new_prefixes=dict(detector=8,execution=10),
        qualified=[],goal_status='active;not achieved',
        note='Zero cost adds one scenario,no new hypothesis;earlier untracked research remains additional selection.'))
    z=control['metrics']
    md='''# AVWAP v7: kết quả 5 năm

**Chưa đạt mục tiêu.** Giữ Fresh; bản riêng cần55–60% thắng,5–10 lệnh/tuần,không tuần trống và edge sau phí.

Đã khóa và chạy5 giả thuyết/15 kịch bản LOW–BASE–STRESS. Thêm1 đối chứng không phí được khóa riêng sau kết quả chính để phân biệt tín hiệu với ảnh hưởng chi phí. Tổng ít nhất87 giả thuyết/334 kịch bản; đối chứng không phí không được coi là giải pháp giao dịch thực.

M1 HLC3 có trọng số tick_volume broker. Toàn bộ real_volume=0; đây là proxy hoạt động quote,không phải giá bình quân giao dịch tập trung. Điểm neo là swing M15 chỉ biết sau2 nến phải đóng,hoặc quote M1 đầu tiên của ngày feed. Chỉ sử dụng phút đã đóng,đủ liên tục,volume dương. Thử retest đầu tiên sau move-away và slope cùng chiều;SL ngoài excursion M5;TP0,8R;Fresh0,5R trong combo. Nguồn ý tưởng:[Brian Shannon/Alphatrends](https://alphatrends.net/anchored-vwap/);ngưỡng XAUUSD là giả thuyết riêng,không phải preset của tác giả.

## BASE:25/10/2021 đến trước25/10/2026

Phí giả định:spread0,30 giá,slip0,01,commission khứ hồi0,07 giá. R tính theoSLban đầu,đã trừphí;không phải%tài khoản.

| Bản | Lệnh | Thắng | PF | NetR | TB/tuần | Tuần0lệnh | Tuần5–10 |
|---|---:|---:|---:|---:|---:|---:|---:|
'''
    for row in rows:
        if row['cost']!='BASE':continue
        m=row['metrics'];freq=m['frequency']
        md+=f"|{row['name']}|{m['n']}|{m['win_rate']:.2f}%|{m['pf']:.3f}|{m['total_r']:+.2f}|{freq['mean']:.2f}|{len(freq['empty_weeks'])}|{freq['weeks_with_5_to_10']}/{freq['weeks']}|\n"
    md+=f'''
Không có cấu hình nào dương ở LOW/BASE/STRESS. Đối chứng SWING_AVWAP không spread/slip/commission:{z['n']}lệnh,{z['win_rate']:.2f}% thắng,PF{z['pf']:.3f},net{z['total_r']:+.2f}R. Đây là chi phí giả tưởng bằng0,chỉ phục vụ chẩn đoán. Các tập fills và thời gian giữ có thể khác nhau giữa mức phí,không quy mọi chênh lệchR thành một khoản phí tiền mặt.

116 tests qua;8 prefix detector và10 prefix execution exact. Nhãn phí và phép trừ gross/commission/net của15 kịch bản chính đã audit. Hash Fresh không đổi. M1 adverse-first,một vị thế,max2fills/ngày/10tuần;giờfeed08–19,thoát trước21 vàmax120phút. Thống kê đủ261tuần có dữ liệu. Bootstrap tháng hiệu chỉnh87giả thuyết;mọi dữ liệu đã xem trước,chỉ gọi hồi cứu.

SWING_AVWAP/BASE có538/1676fills ởSL tối thiểu2 giá,risk median2,745;phí commission tổng40,20R. Một phép thử có cơ sở kế tiếp là dùng mức vô hiệu hóa của swingM15 đã xác nhận làmSL ngoài cả swing và retest,giữ nguyên tín hiệu/TP/phí/caps. Không scan thêm một dãy độ rộngSL. Cần khóa riêng trước kết quả và đếm thêm;chưa triển khai ở checkpoint này.

Không đặt broker orders,cài đè,gửi tin ngoài hoặc xây native khi chưa có ứng viên. Phí thực,clock/DST,tick/news/prop package chưa xác minh. Kết quả không bảo đảm lợi nhuận tương lai.
'''
    (run/'RESEARCH_CHECKPOINT.md').write_text(md,encoding='utf-8')
    write_json(run/'CHECKPOINT_MANIFEST.json',dict(input_data_sha256=lock['data_sha256'],
        scripts={p:sha(w.ROOT/p) for p in ['scripts/research_scalp_avwap_v7.py','scripts/audit_scalp_avwap_v7.py',
                  'scripts/finalize_scalp_avwap_v7.py','tests/test_research_scalp_avwap_v7.py']},
        goal_status='active',qualified=[],previous_turn_classification='progress'))
    print('ZERO CONTROL',z['n'],round(z['win_rate'],2),round(z['pf'],3),round(z['total_r'],2),flush=True)
    print('V7 CHECKPOINT:87 hypotheses/334 scenarios;qualified0;Fresh unchanged',flush=True)


if __name__=='__main__':main()
