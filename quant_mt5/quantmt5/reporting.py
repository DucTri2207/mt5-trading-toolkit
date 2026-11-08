"""One-process analysis packet; watch locations are descriptive, never new gates."""
from __future__ import annotations

from copy import deepcopy

from .util import iso_utc, now_utc, parse_utc


def candidate_priority(c: dict):
    live = "ENTRY_WINDOW" in (c.get("plan_window") or {}).values()
    return (not live, -parse_utc(c["ready_at"]))


def current_window(c: dict, snap: dict, computed_at: float) -> dict:
    valid = "ENTRY_WINDOW" in (c.get("plan_window") or {}).values()
    deadline = parse_utc(c["entry_deadline_at"]) if c.get("entry_deadline_at") else None
    age = computed_at - parse_utc(snap["as_of_utc"])
    sv = (snap.get("symbols") or {}).get(c["symbol"]) or {}
    # Snapshot validity is not present-time tradability or an account/risk approval.
    timely = valid and deadline is not None and computed_at < deadline and 0 <= age <= 90
    fresh = sv.get("market_state") == "FRESH"
    costs = (sv.get("economics") or {}).get("status") in ("ASSUMED", "KNOWN")
    return {"valid_at_as_of": valid, "snapshot_age_s": round(age, 3),
            "entry_window_at_computation": bool(timely and fresh and costs),
            "actionable_now": False, "requires_fresh_quote_and_account_checks": True,
            "current_status": "RECHECK_QUOTE_REQUIRED" if timely and fresh and costs else "EXPIRED_OR_BLOCKED",
            "deadline": c.get("entry_deadline_at")}


def watch_zones(snap: dict, fabio: dict | None = None) -> list[dict]:
    out = []
    for ep in snap.get("episodes", []):
        if ep.get("state_at_as_of", ep.get("state")) != "WATCHING_RETEST":
            continue
        level = ep["U"] if ep["side"] == "LONG" else ep["D"]
        out.append({"symbol": ep["symbol"], "setup": "A", "side": ep["side"],
                    "state": "WATCHING_RETEST", "episode_id": ep["episode_id"],
                    "anchor_at": ep.get("anchor_at"), "known_at": ep.get("breakout_available_at"),
                    "zone_low": level - ep["delta"], "zone_high": level + ep["delta"],
                    "atr_frozen": ep["atr_frozen"], "expires_at": ep["expires_at"],
                    "invalidation": {"closed_M5_below" if ep["side"] == "LONG" else "closed_M5_above":
                                     level - ep["delta"] if ep["side"] == "LONG" else level + ep["delta"]},
                    "trigger": "Retest + closed M5 price response + unchanged A branch gates; not an entry yet",
                    "basis": "EXACT_FROZEN_A_ANCHOR", "actionable_now": False})
    for symbol, fr in (fabio or {}).items():
        for family, fam in (fr.get("families") or {}).items():
            location = (fam.get("gates") or {}).get("location") or {}
            if not location:
                continue
            out.append({"symbol": symbol, "setup": family, "side": fam.get("side"),
                        "state": fam.get("decision"), "location": location,
                        "invalidation": fam.get("invalidation"), "expires_at": fam.get("expires_at"),
                        "missing": fam.get("missing"), "basis": fr.get("cvd"),
                        "actionable_now": False})
    return out


def build_baseline_packet(snap: dict, computed_at: float | None = None) -> dict:
    """Return every detector candidate without waiting for optional interpretation."""
    computed = now_utc() if computed_at is None else computed_at
    candidates = deepcopy(sorted(snap.get("candidates", []), key=candidate_priority))
    return {"schema_version": "A_MT5_BASELINE_V1", "stage": "BASELINE",
            "snapshot_id": snap["snapshot_id"], "as_of": snap["as_of_utc"],
            "computed_at": iso_utc(computed), "context_state": "PENDING",
            "candidates": candidates, "market": {}, "cards": {},
            "watch_zones": watch_zones(snap), "currency_groups": {}, "errors": [],
            "news_handling": "USER_MANAGED", "news_checked_by_system": False,
            "deferred_cards": [{"candidate_id": c["candidate_id"], "symbol": c["symbol"],
                                "status": "DEFERRED_DEEP_ANALYSIS", "reason": "CONTEXT_PENDING"}
                               for c in candidates]}


def render_evening_context(analysis: dict, deep_ids: set[str]) -> list[str]:
    """Compact Vietnamese explanation; detailed provenance stays in the sibling JSON."""
    contexts = analysis.get("evening_context") or {}
    if not contexts:
        return []
    labels = {"UP_BIAS": "nghiêng tăng", "DOWN_BIAS": "nghiêng giảm", "MIXED_OR_FLAT": "hỗn hợp/đi ngang",
              "SUPPORTS": "thuận hướng", "CONTRADICTS": "ngược hướng", "NEUTRAL": "trung tính",
              "UNKNOWN": "chưa đủ dữ liệu", "ABOVE_REFERENCE_VALUE": "trên vùng value tham chiếu",
              "BELOW_REFERENCE_VALUE": "dưới vùng value tham chiếu", "INSIDE_REFERENCE_VALUE": "trong vùng value tham chiếu"}
    def label(value):
        return labels.get(value, str(value) if value is not None else "chưa có")
    def numeric(value):
        return f"{value:.6g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "—"
    def evidence_keys(refs):
        return ", ".join(str(r.get("record_key") or r.get("evidence_id") or r.get("artifact_kind"))
                         if isinstance(r, dict) else str(r) for r in refs)
    lines = ["## Bản đồ cơ hội ca tối — MT5-only", "",
             "Nhãn H1 chỉ mô tả hướng giá, không là gate bổ sung cho A. Vùng/mục tiêu tham chiếu không thay entry/SL/TP.",
             "Hoạt động tick của feed không chứng minh ý định cá mập hoặc dòng tiền toàn thị trường; nguồn chi tiết trong JSON cùng báo cáo.", ""]
    for symbol, context in contexts.items():
        price = context.get("price_reference") or {}
        flow = context.get("flow") or {}
        lines += [f"### {symbol} — H1 {label(context.get('direction_context'))}", "",
                  f"- M5 đóng: {numeric(price.get('close'))} ({price.get('bar_close_at') or 'UNKNOWN'}); vị trí: {label(context.get('value_location'))}.",
                  f"- Context: {context.get('context_state')} · thời điểm {context.get('as_of')} · không phải xác nhận có thể đặt lệnh ngay."]
        if flow:
            lines.append(f"- Hoạt động MT5: basis `{flow.get('volume_basis', 'UNKNOWN')}`, proxy={flow.get('is_proxy', 'UNKNOWN')}, "
                         f"status={flow.get('status', 'UNKNOWN')}, coverage={flow.get('coverage_window', 'UNKNOWN')}; "
                         f"CVD={numeric(flow.get('current_cvd'))}, thay đổi gần đây={numeric(flow.get('recent_cvd_change'))}. "
                         "Không so qua gap/reset; proxy không phải volume khớp lệnh độc lập.")
        else:
            lines.append("- Flow: chưa có dữ liệu usable từ cùng snapshot; không dùng làm lý do loại A.")
        movement = context.get("relative_movement") or {}
        if movement:
            lines.append("- Dịch chuyển chuẩn hóa ATR đầu kỳ: " + "; ".join(
                f"{h}h={numeric((movement.get(h) or {}).get('value'))} ({(movement.get(h) or {}).get('quality', 'UNKNOWN')})"
                for h in ("1", "4")) + ". Đây là mô tả tương đối, không xác suất thắng.")
        for window in context.get("reference_windows", []):
            complete = window.get("lifecycle") == "COMPLETED"
            hi, lo = (window.get("high"), window.get("low")) if complete else (window.get("observed_high"), window.get("observed_low"))
            lines.append(f"- {window.get('window_id')}: {window.get('lifecycle')}, "
                         f"{'biên đầy đủ' if complete else 'biên phần đã quan sát'} {numeric(lo)}–{numeric(hi)}, "
                         f"coverage {window.get('observed_count', 0)}/{window.get('expected_count', 0)} M5; "
                         f"time-quality={window.get('time_quality')}. Cửa sổ nghiên cứu, không lịch broker.")
        scenarios = context.get("scenarios") or []
        if scenarios:
            lines += ["", "| A / vùng chờ | Hướng | H1 so với A | Frozen zone | Phản chứng M5 | Mức tham chiếu gần nhất (không đổi TP) |",
                      "|---|---|---|---|---|---|"]
            for scenario in scenarios:
                zone = scenario.get("frozen_zone") or {}
                condition = scenario.get("refuting_condition") or {}
                target = (scenario.get("reference_targets") or [{}])[0]
                ident = scenario.get("candidate_ref") or f"WATCH {scenario.get('episode_ref')}"
                lines.append(f"| {ident} | {scenario.get('preferred_side')} | {label(scenario.get('context_status'))} | "
                             f"{numeric(zone.get('low'))}–{numeric(zone.get('high'))} | "
                             f"{condition.get('operator')} {numeric(condition.get('level'))} | "
                             f"{target.get('level_id', 'chưa có')} {numeric(target.get('price'))} |")
            lines.append("")
            for scenario in scenarios:
                if scenario.get("candidate_ref") not in deep_ids:
                    continue
                lines += [f"- `{scenario['candidate_ref']}`: kịch bản theo {scenario.get('preferred_side')} giữ trigger/gate/plan A gốc. "
                          f"Cửa sổ entry: {scenario.get('plan_window')}; deadline {scenario.get('entry_deadline_at')}. "
                          "Điều kiện đóng M5 xuyên biên trong bảng là phản chứng cho kịch bản, không phải sửa SL.",
                          f"  Dữ kiện thuận: {evidence_keys(scenario.get('supporting_refs') or []) or 'chưa có H1 ủng hộ được đo'}; "
                          f"nghịch: {evidence_keys(scenario.get('contradicting_refs') or []) or 'chưa có H1 phản bác được đo'}. "
                          "Đây là giá-derived, không đếm thành nhiều phiếu độc lập."]
        else:
            lines.append("- Chưa có chủ thể A/episode: chỉ quan sát vùng và chờ engine xác nhận, không sinh entry/SL/TP mới.")
        if context.get("missing"):
            lines.append("- Thiếu dữ kiện: " + "; ".join(f"{m.get('field')}: {m.get('reason')}" for m in context["missing"]))
        lines.append("")
    strength = analysis.get("currency_strength") or {}
    if strength:
        lines += ["### Sức mạnh tương đối trong rổ FX đã ghim", "",
                  "Mean của chuyển động chuẩn hóa ATR; rank chỉ khi đủ dữ liệu so sánh. Không áp cho vàng/chỉ số, không lọc A.", "",
                  "| Tiền tệ | 1h / rank | 4h / rank | Số cặp đã dùng |", "|---|---|---|---|"]
        for currency, horizons in sorted(strength.items()):
            one, four = horizons.get("1") or {}, horizons.get("4") or {}
            lines.append(f"| {currency} | {numeric(one.get('comparable_value'))} / {one.get('rank')} | "
                         f"{numeric(four.get('comparable_value'))} / {four.get('rank')} | {one.get('count', 0)} / {four.get('count', 0)} |")
        lines.append("")
    return lines


def analyze_snapshot(snap: dict, max_cards: int = 8, fabio: dict | None = None) -> dict:
    from .context import build_market_context, opportunity_card, check_snapshot_config
    from .analysis_cache import analysis_scope
    from .config import ConfigBundleError
    from .data import DataVersionMismatch, ChunkCorrupt
    from .evening_context import build_evening_context, build_currency_strength
    check_snapshot_config(snap)
    computed = now_utc()
    result = {"stage": "FULL", "snapshot_id": snap["snapshot_id"], "as_of": snap["as_of_utc"],
              "computed_at": iso_utc(computed), "market": {}, "cards": {},
              "watch_zones": watch_zones(snap, fabio), "news": "USER_MANAGED",
              "news_handling": "USER_MANAGED", "news_checked_by_system": False,
              "currency_groups": {}, "errors": [], "max_cards": max_cards}
    candidates = sorted(snap.get("candidates", []), key=candidate_priority)
    result["candidates"] = deepcopy(candidates)
    result["deferred_cards"] = [{"candidate_id": c["candidate_id"], "symbol": c["symbol"],
                                  "status": "DEFERRED_DEEP_ANALYSIS", "reason": "MAX_CARDS_LIMIT"}
                                 for c in candidates[max(0, max_cards):]]
    with analysis_scope():
        for symbol in snap["universe"]:
            sv = (snap.get("symbols") or {}).get(symbol) or {}
            if sv.get("status") == "ERROR":
                result["market"][symbol] = {"status": "UNAVAILABLE", "item_state": "UNKNOWN",
                                            "reason": sv.get("reason") or "SNAPSHOT_SYMBOL_UNAVAILABLE"}
                continue
            try:
                result["market"][symbol] = build_market_context(snap["snapshot_id"], symbol, groups=["ema", "er"])
            except (DataVersionMismatch, ChunkCorrupt, ConfigBundleError):
                # Corrupt core evidence is not an optional analytical failure.
                raise
            except Exception as exc:
                result["market"][symbol] = {"status": "UNAVAILABLE", "item_state": "ERROR", "reason": str(exc)}
                result["errors"].append({"symbol": symbol, "reason": str(exc)})
        for c in candidates[:max(0, max_cards)]:
            try:
                card = opportunity_card(snap["snapshot_id"], c["candidate_id"])
                card["current_window"] = current_window(c, snap, computed)
                result["cards"][c["candidate_id"]] = card
            except (DataVersionMismatch, ChunkCorrupt, ConfigBundleError):
                raise
            except Exception as exc:
                result["cards"][c["candidate_id"]] = {"status": "ERROR", "reason": str(exc)}
                result["errors"].append({"candidate_id": c["candidate_id"], "reason": str(exc)})
        result["evening_context"] = build_evening_context(snap, result["market"], fabio)
        result["currency_strength"] = build_currency_strength(result["evening_context"], snap["universe"])
    for symbol, market in result["market"].items():
        metadata = market.get("asset_metadata") or {}
        if metadata.get("asset_class") == "FX" and metadata.get("status") == "OK":
            for currency in (metadata.get("base_currency"), metadata.get("quote_currency")):
                if currency:
                    result["currency_groups"].setdefault(currency, []).append(symbol)
    for symbol, fr in (fabio or {}).items():
        if fr.get("status") == "ERROR" and (snap.get("symbols", {}).get(symbol) or {}).get("status") != "ERROR":
            result["errors"].append({"symbol": symbol, "component": "fabio", "reason": fr.get("reason") or fr.get("report_error")})
    result["context_state"] = "PARTIAL_FAILED" if result["errors"] else "COMPLETE"
    ready = now_utc()
    result["analysis_ready_at"] = iso_utc(ready)
    for c in candidates[:max(0, max_cards)]:
        card = result["cards"].get(c["candidate_id"])
        if card and card.get("status") == "OK":
            card["current_window"] = current_window(c, snap, ready)
    return result
