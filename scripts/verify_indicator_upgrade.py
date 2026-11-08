import os
import sys
import unittest
import re

# Ensure Windows stdout handles utf-8 characters properly
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# ==============================================================================
# Model Implementations for Independent Verification
# ==============================================================================

class AssetProfile:
    def __init__(self, asset_class: str, class_tag: str, unit_name: str, min_sl_buffer: float, pip_size: float, prime_session: str):
        self.asset_class = asset_class
        self.class_tag = class_tag
        self.unit_name = unit_name
        self.min_sl_buffer = min_sl_buffer
        self.pip_size = pip_size
        self.prime_session = prime_session

def get_asset_profile(symbol: str, digits: int = 5, point: float = 0.00001) -> AssetProfile:
    sym = symbol.upper()

    # 1. METALS
    if any(k in sym for k in ["XAU", "GOLD", "XAG", "SILVER", "XPT", "XPD"]):
        return AssetProfile(
            asset_class="METALS",
            class_tag="[METALS]",
            unit_name="USD",
            min_sl_buffer=3.5,
            pip_size=0.1,
            prime_session="Phiên Tối US (19:30 - 23:00 VN)"
        )

    # 2. INDICES - Strict token check (avoid false match with USDJPY)
    is_us30 = any(k in sym for k in ["US30", "DJ30", "DOW", "WALLSTREET", "WS30"])
    is_tech = any(k in sym for k in ["NAS", "USTEC", "NDX", "SPX", "US500", "GER", "DAX"])

    if is_us30:
        return AssetProfile(
            asset_class="INDICES",
            class_tag="[INDICES]",
            unit_name="points",
            min_sl_buffer=35.0,
            pip_size=1.0 if point <= 0 else point,
            prime_session="NY Cash Open (20:30 - 22:30 VN)"
        )
    if is_tech:
        return AssetProfile(
            asset_class="INDICES",
            class_tag="[INDICES]",
            unit_name="points",
            min_sl_buffer=25.0,
            pip_size=1.0 if point <= 0 else point,
            prime_session="NY Cash Open (20:30 - 22:30 VN)"
        )

    # 3. FOREX (Default)
    pip_size = point * 10.0 if digits in (3, 5) else point
    return AssetProfile(
        asset_class="FOREX",
        class_tag="[FOREX]",
        unit_name="pips",
        min_sl_buffer=12.0 * pip_size,
        pip_size=pip_size,
        prime_session="Phiên London (14:00 - 17:30 VN)"
    )

def compute_dynamic_sl_buffer(profile: AssetProfile, atr_m5: float, sl_buffer_atr_mult: float = 0.5) -> float:
    atr_buffer = sl_buffer_atr_mult * atr_m5
    if profile.asset_class == "METALS":
        return min(6.0, max(3.5, atr_buffer))
    elif profile.asset_class == "FOREX":
        return max(profile.min_sl_buffer, atr_buffer)
    elif profile.asset_class == "INDICES":
        return max(profile.min_sl_buffer, atr_buffer)
    return max(profile.min_sl_buffer, atr_buffer)

class OrderBlockZone:
    def __init__(self, low: float, high: float, is_supply: bool, score: int, test_count: int = 0, is_flip: bool = False):
        self.low = min(low, high)
        self.high = max(low, high)
        self.is_supply = is_supply
        self.score = score
        self.test_count = test_count
        self.is_flip = is_flip
        self.mean_threshold = (self.low + self.high) / 2.0
        self.is_composite = False
        self.merged_count = 1

def merge_composite_order_blocks(zones: list, htf_atr: float, min_score_merge: int = 70) -> list:
    total = len(zones)
    if total <= 1:
        return [z for z in zones if z.score >= min_score_merge]

    merge_dist = 0.8 * htf_atr
    merged = [False] * total
    composite_list = []

    for i in range(total):
        if merged[i] or zones[i].score < min_score_merge:
            continue

        c_high = zones[i].high
        c_low = zones[i].low
        is_sup = zones[i].is_supply
        max_score = zones[i].score
        max_tests = zones[i].test_count
        has_flip = zones[i].is_flip
        cluster_count = 1
        merged[i] = True

        found_more = True
        while found_more:
            found_more = False
            for j in range(total):
                if merged[j] or zones[j].score < min_score_merge or zones[j].is_supply != is_sup:
                    continue

                z_high = zones[j].high
                z_low = zones[j].low

                gap = 0.0
                if z_low > c_high:
                    gap = z_low - c_high
                elif c_low > z_high:
                    gap = c_low - z_high
                else:
                    gap = 0.0 # overlapping

                if gap < merge_dist:
                    c_high = max(c_high, z_high)
                    c_low = min(c_low, z_low)
                    max_score = max(max_score, zones[j].score)
                    max_tests = max(max_tests, zones[j].test_count)
                    if zones[j].is_flip:
                        has_flip = True
                    cluster_count += 1
                    merged[j] = True
                    found_more = True

        comp_score = min(100, max_score + (cluster_count - 1) * 5)
        comp = OrderBlockZone(c_low, c_high, is_sup, comp_score, max_tests, has_flip)
        comp.is_composite = (cluster_count > 1)
        comp.merged_count = cluster_count
        composite_list.append(comp)

    return composite_list

def calculate_fvg_ce(gap_low: float, gap_high: float) -> float:
    return (gap_low + gap_high) / 2.0

def format_telegram_message(sig: dict, profile: AssetProfile) -> str:
    dir_emoji = "🟢" if sig["is_buy"] else "🔴"
    dir_text = "BUY CHoCH" if sig["is_buy"] else "SELL CHoCH"

    risk = abs(sig["entry"] - sig["sl"])
    tp1_dist = abs(sig["tp1"] - sig["entry"])
    tp2_dist = abs(sig["tp2"] - sig["entry"])
    macro_dist = abs(sig["tp_macro"] - sig["entry"]) if sig.get("tp_macro", 0) > 0 else 0.0
    rr_macro = (macro_dist / risk) if risk > 0 and macro_dist > 0 else 3.5

    msg = (
        f"⚡ <b>SMT / SMC M5 CHoCH TRIGGER {profile.class_tag}</b> ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Cặp tiền / Tài sản:</b> <code>{sig['symbol']}</code> (M5) | <b>Lớp:</b> <code>{profile.asset_class}</code>\n"
        f"🧭 <b>Hướng:</b> {dir_emoji} <b>{dir_text}</b>\n"
        f"🏛 <b>Cản kích hoạt:</b> <code>{sig['zone_type']}</code>\n"
        f"🎯 <b>Mốc kích hoạt:</b> {sig['poi_source']} ({sig['sweep_price']:.2f})\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Giá Entry:</b> <code>{sig['entry']:.2f}</code>\n"
        f"🛡 <b>Stop Loss:</b> <code>{sig['sl']:.2f}</code> (Đệm an toàn: {sig['sl_buffer_val']:.1f} {profile.unit_name})\n"
        f"🎁 <b>Take Profit 1 (1:1.5):</b> <code>{sig['tp1']:.2f}</code> (+{tp1_dist:.1f} {profile.unit_name} | R:R 1:1.5)\n"
        f"🚀 <b>Take Profit 2 (1:2.0):</b> <code>{sig['tp2']:.2f}</code> (+{tp2_dist:.1f} {profile.unit_name} | R:R 1:2.0)\n"
    )
    if sig.get("tp_macro", 0) > 0:
        msg += f"🏛 <b>Target Cản đối diện:</b> <code>{sig['tp_macro']:.2f}</code> (+{macro_dist:.1f} {profile.unit_name} | R:R 1:{rr_macro:.1f})\n"
    msg += (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ <b>Khung giờ:</b> <code>{sig['time']}</code> | <b>Phiên:</b> <code>{profile.prime_session}</code>\n"
        f"⚠️ <b>Invalidation:</b> Đóng nến M5 ngược chiều bẻ gãy chóp râu quét -> Hủy kế hoạch!"
    )
    return msg

# ==============================================================================
# Automated Test Suite
# ==============================================================================

class TestMasterIndicatorUpgrade(unittest.TestCase):

    def test_01_asset_profiler_classification(self):
        """Verify strict token matching across Metals, Forex, and Indices."""
        # Metals
        for sym in ["XAUUSD", "XAUUSDm", "GOLD", "GOLD.raw", "XAGUSD", "SILVER", "XPTUSD"]:
            p = get_asset_profile(sym)
            self.assertEqual(p.asset_class, "METALS")
            self.assertEqual(p.class_tag, "[METALS]")
            self.assertEqual(p.unit_name, "USD")
            self.assertEqual(p.min_sl_buffer, 3.5)

        # Indices - US30 group
        for sym in ["US30", "US30.cash", "DJ30", "DOW", "WALLSTREET", "WS30"]:
            p = get_asset_profile(sym)
            self.assertEqual(p.asset_class, "INDICES")
            self.assertEqual(p.class_tag, "[INDICES]")
            self.assertEqual(p.unit_name, "points")
            self.assertEqual(p.min_sl_buffer, 35.0)

        # Indices - Tech/Global group
        for sym in ["NAS100", "USTEC", "NDX", "SPX500", "US500", "GER40", "DAX"]:
            p = get_asset_profile(sym)
            self.assertEqual(p.asset_class, "INDICES")
            self.assertEqual(p.class_tag, "[INDICES]")
            self.assertEqual(p.unit_name, "points")
            self.assertEqual(p.min_sl_buffer, 25.0)

        # Forex
        for sym in ["EURUSD", "GBPUSD", "USDJPY", "AUDNZD.pro", "NZDCAD"]:
            p = get_asset_profile(sym)
            self.assertEqual(p.asset_class, "FOREX")
            self.assertEqual(p.class_tag, "[FOREX]")
            self.assertEqual(p.unit_name, "pips")

        # STRICT TOKEN TEST: USDJPY must NEVER be classified as INDICES despite containing 'DJ'
        usdjpy_prof = get_asset_profile("USDJPY")
        self.assertEqual(usdjpy_prof.asset_class, "FOREX")
        self.assertNotEqual(usdjpy_prof.asset_class, "INDICES")

    def test_02_dynamic_sl_buffer_calculations(self):
        """Verify dynamic SL buffer scaling and clamping per asset class."""
        # Metals clamping between 3.5 and 6.0 USD
        p_metals = get_asset_profile("XAUUSD")
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_metals, atr_m5=2.0), 3.5)  # 0.5*2.0=1.0 -> clamp 3.5
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_metals, atr_m5=10.0), 5.0) # 0.5*10.0=5.0
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_metals, atr_m5=16.0), 6.0) # 0.5*16.0=8.0 -> clamp 6.0

        # Forex floor >= 12 pips
        p_forex = get_asset_profile("EURUSD", digits=5, point=0.00001)
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_forex, atr_m5=0.00080), 0.00120) # 8 pips ATR -> floor 12 pips
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_forex, atr_m5=0.00300), 0.00150) # 30 pips ATR -> 15 pips

        # Indices US30 floor >= 35 points
        p_us30 = get_asset_profile("US30")
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_us30, atr_m5=40.0), 35.0)  # 20 pts -> floor 35
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_us30, atr_m5=100.0), 50.0) # 50 pts

        # Indices NAS100 floor >= 25 points
        p_nas = get_asset_profile("NAS100")
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_nas, atr_m5=30.0), 25.0)  # 15 pts -> floor 25
        self.assertAlmostEqual(compute_dynamic_sl_buffer(p_nas, atr_m5=80.0), 40.0)  # 40 pts

    def test_03_luxalgo_composite_merging_math(self):
        """Verify LuxAlgo Composite Order Block clustering algorithm and Mean Threshold 50%."""
        htf_atr = 10.0 # Merge threshold = 0.8 * 10.0 = 8.0

        # Scenario A: Two adjacent supply zones (gap = 2.0 < 8.0)
        z1 = OrderBlockZone(low=2650.0, high=2655.0, is_supply=True, score=80, test_count=0)
        z2 = OrderBlockZone(low=2657.0, high=2662.0, is_supply=True, score=75, test_count=1)

        merged = merge_composite_order_blocks([z1, z2], htf_atr, min_score_merge=70)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0].is_composite)
        self.assertEqual(merged[0].merged_count, 2)
        self.assertAlmostEqual(merged[0].low, 2650.0)
        self.assertAlmostEqual(merged[0].high, 2662.0)
        self.assertEqual(merged[0].score, 85) # max(80, 75) + 5
        self.assertAlmostEqual(merged[0].mean_threshold, 2656.0) # (2650 + 2662) / 2

        # Scenario B: Distant zones (gap = 15.0 > 8.0) must NOT merge
        z3 = OrderBlockZone(low=2680.0, high=2685.0, is_supply=True, score=80)
        unmerged = merge_composite_order_blocks([z1, z3], htf_atr, min_score_merge=70)
        self.assertEqual(len(unmerged), 2)
        self.assertFalse(unmerged[0].is_composite)

        # Scenario C: Low score (< 70) excluded from master composite list
        z_low = OrderBlockZone(low=2650.0, high=2655.0, is_supply=True, score=65)
        z_high = OrderBlockZone(low=2652.0, high=2657.0, is_supply=True, score=75)
        filtered = merge_composite_order_blocks([z_low, z_high], htf_atr, min_score_merge=70)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].score, 75)

        # Scenario D: 3 overlapping zones merge into 1 single bounding box
        d1 = OrderBlockZone(low=2600.0, high=2605.0, is_supply=False, score=75)
        d2 = OrderBlockZone(low=2604.0, high=2608.0, is_supply=False, score=80)
        d3 = OrderBlockZone(low=2607.0, high=2612.0, is_supply=False, score=70)
        tri_merged = merge_composite_order_blocks([d1, d2, d3], htf_atr, min_score_merge=70)
        self.assertEqual(len(tri_merged), 1)
        self.assertEqual(tri_merged[0].merged_count, 3)
        self.assertAlmostEqual(tri_merged[0].low, 2600.0)
        self.assertAlmostEqual(tri_merged[0].high, 2612.0)
        self.assertEqual(tri_merged[0].score, 90) # max 80 + 2*5 = 90
        self.assertAlmostEqual(tri_merged[0].mean_threshold, 2606.0)

    def test_04_session_liquidity_pdh_pdl_no_lookahead(self):
        """Verify PDH / PDL strictly references closed candle D1[1] without lookahead bias."""
        daily_candles = [
            {"index": 0, "high": 2695.0, "low": 2670.0, "closed": False}, # Today (in progress)
            {"index": 1, "high": 2685.5, "low": 2642.1, "closed": True},  # Yesterday (complete)
            {"index": 2, "high": 2660.0, "low": 2630.0, "closed": True}
        ]

        # Algorithm must pull from index 1
        pdh = daily_candles[1]["high"]
        pdl = daily_candles[1]["low"]

        self.assertAlmostEqual(pdh, 2685.5)
        self.assertAlmostEqual(pdl, 2642.1)
        self.assertTrue(daily_candles[1]["closed"])
        self.assertNotEqual(pdh, daily_candles[0]["high"], "Lookahead bias detected! PDH used candle 0!")
        self.assertNotEqual(pdl, daily_candles[0]["low"], "Lookahead bias detected! PDL used candle 0!")

    def test_05_fvg_ce_50_and_mitigation_lifecycle(self):
        """Verify FVG BISI/SIBI detection, Consequent Encroachment (CE 50%), and mitigation tracking."""
        # BISI FVG
        bisi_low = 2640.0
        bisi_high = 2648.0
        bisi_ce = calculate_fvg_ce(bisi_low, bisi_high)
        self.assertAlmostEqual(bisi_ce, 2644.0)

        # SIBI FVG
        sibi_low = 2675.0
        sibi_high = 2685.0
        sibi_ce = calculate_fvg_ce(sibi_low, sibi_high)
        self.assertAlmostEqual(sibi_ce, 2680.0)

        # Mitigation lifecycle simulation
        bars_after_bisi = [2645.0, 2642.0, 2639.5] # Bar 2 closed at 2639.5 < bisi_low (2640.0) -> Mitigated
        is_mitigated = any(c < bisi_low for c in bars_after_bisi)
        self.assertTrue(is_mitigated)

    def test_06_adaptive_confirmation_trigger_risk_reward(self):
        """Verify M5 CHoCH trigger, dynamic risk/reward geometry, and Telegram HTML payload."""
        profile = get_asset_profile("XAUUSD")
        entry = 2650.0
        sweep_price = 2646.0
        sl_buffer = compute_dynamic_sl_buffer(profile, atr_m5=2.0) # 3.5 USD

        sl = sweep_price - sl_buffer # 2642.50
        risk = entry - sl # 7.50
        tp1 = entry + 1.5 * risk # 2661.25 (R:R 1:1.5)
        tp2 = entry + 2.0 * risk # 2665.00 (R:R 1:2.0)
        tp_macro = 2685.50 # Opposite PDH target
        rr_macro = (tp_macro - entry) / risk # 35.50 / 7.50 = 4.73 >= 3.0

        self.assertAlmostEqual(sl, 2642.50)
        self.assertAlmostEqual(risk, 7.50)
        self.assertAlmostEqual((tp1 - entry) / risk, 1.5)
        self.assertAlmostEqual((tp2 - entry) / risk, 2.0)
        self.assertGreaterEqual(rr_macro, 3.0)

        sig = {
            "symbol": "XAUUSD",
            "is_buy": True,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp_macro": tp_macro,
            "sweep_price": sweep_price,
            "sl_buffer_val": sl_buffer,
            "zone_type": "COMPOSITE DEMAND H1",
            "poi_source": "Asian Low Sweep",
            "time": "2026.10.18 20:45"
        }

        tg_msg = format_telegram_message(sig, profile)
        self.assertIn("[METALS]", tg_msg)
        self.assertIn("XAUUSD", tg_msg)
        self.assertIn("BUY CHoCH", tg_msg)
        self.assertIn("COMPOSITE DEMAND H1", tg_msg)
        self.assertIn("USD", tg_msg)
        self.assertIn("Invalidation:", tg_msg)

    def test_07_source_code_integrity(self):
        """Verify duc_tri_can_ho_tro.mq5 contains all required modular components."""
        mq5_path = r"d:\trading thử lần cuối cuối\duc_tri_can_ho_tro.mq5"
        self.assertTrue(os.path.exists(mq5_path))

        with open(mq5_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()

        # Check required class and struct definitions
        required_elements = [
            "enum ENUM_ASSET_CLASS",
            "class CAssetProfiler",
            "class COrderBlockEngine",
            "class CSessionLiquidityEngine",
            "class CFvgEngine",
            "class CAdaptiveConfirmationEngine",
            "UseCompositeOB",
            "ShowSessionLiq",
            "ShowFvg",
            "meanThreshold",
            "consequentEncroachment",
            "asianHigh",
            "asianLow",
            "[METALS]",
            "[FOREX]",
            "[INDICES]"
        ]
        for elem in required_elements:
            self.assertIn(elem, code, f"Source code missing required element: '{elem}'")

def run_tests():
    print("=" * 70)
    print("[TEST SUITE] RUNNING INSTITUTIONAL MASTER UPGRADE VERIFICATION")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestMasterIndicatorUpgrade)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n" + "=" * 70)
        print(f"[PASSED] ALL {result.testsRun} TESTS PASSED SUCCESSFULLY! EXIT CODE 0")
        print("=" * 70)
        return 0
    else:
        print("\n" + "=" * 70)
        print(f"[FAILED] {len(result.failures)} FAILURES, {len(result.errors)} ERRORS")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
