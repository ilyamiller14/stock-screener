"""Tests for screener.emailer — v2 score_breakdown rendering in per-pick card."""
from __future__ import annotations

import pytest

from screener import emailer


def _v2_pick(**overrides):
    """A pick dict in the v2 schema shape (matches what scorer.rank_stocks emits)."""
    base = {
        "ticker": "ATEN",
        "company_name": "A10 Networks, Inc.",
        "sector": "Technology",
        "close": 25.0,
        "change_pct": 1.2,
        "volume": 1_500_000,
        "avg_volume_20d": 1_000_000,
        "high_52w": 26.0,
        "low_52w": 12.0,
        "dist_from_52w_high_pct": 3.8,
        "composite_score": 49.7,
        "score_breakdown": {
            "trend_strength":     85.9,
            "trend_cleanliness":  100.0,
            "rs":                 45.3,
            "base_setup":         27.5,
            "volume_profile":     34.6,
            "raw_setup_score":    58.5,
            "penalty_multiplier": 0.85,
            "penalty_triggered":  ["climactic_mild", "52w_low_mild"],
            "composite_score":    49.7,
        },
        "indicators": {},
        # legacy fields the emailer still pulls for the mini-metrics row
        "ibd_rs_percentile": 78.0,
        "adx_14": 35.0,
        "adx_robust": 33.0,
        "rsi_14": 65.0,
        "cmf_20": 0.08,
        "obv_trend": "rising",
        "ema_aligned": True,
        "near_52w_high": True,
        "vcp_detected": False,
        "squeeze_on": False,
        "squeeze_fired": False,
        "r2_log_60d": 0.92,
        "concentration_60d": 25.0,
        "base_depth_pct": 8.0,
    }
    base.update(overrides)
    return base


class TestStockCardV2:
    def test_renders_v2_category_scores(self):
        """v2 picks must show the actual category scores (not zeros)."""
        html = emailer._stock_card(1, _v2_pick(), "2026-05-15")
        # The five v2 category values must appear in the rendered HTML
        assert "85.9" in html, "trend_strength score missing from email"
        assert "100" in html, "trend_cleanliness score missing"
        assert "45.3" in html, "rs score missing"
        assert "27.5" in html, "base_setup score missing"
        assert "34.6" in html, "volume_profile score missing"

    def test_renders_v2_category_labels(self):
        """Labels must reflect v2 categories, not v1 ('Momentum', 'Pattern' are gone)."""
        html = emailer._stock_card(1, _v2_pick(), "2026-05-15")
        assert "Trend Strength" in html
        assert "Trend Cleanliness" in html
        assert "Base" in html  # 'Base & Setup' or 'Base/Setup'
        assert "Volume Profile" in html or "Volume" in html

    def test_renders_penalties_when_present(self):
        """If penalty_triggered is non-empty, the email should show the triggers + multiplier."""
        html = emailer._stock_card(1, _v2_pick(), "2026-05-15")
        assert "climactic_mild" in html
        assert "52w_low_mild" in html
        # The multiplier should appear (0.85 → "0.85" or "×0.85")
        assert "0.85" in html

    def test_no_penalty_row_when_no_triggers(self):
        """When penalty_triggered is empty, no penalty row should render."""
        pick = _v2_pick()
        pick["score_breakdown"]["penalty_triggered"] = []
        pick["score_breakdown"]["penalty_multiplier"] = 1.0
        html = emailer._stock_card(1, pick, "2026-05-15")
        # The literal word "Penalt" should not appear anywhere if no penalties triggered
        assert "Penalt" not in html, "should not render penalty section when no triggers"

    def test_shows_v2_diagnostic_metrics(self):
        """Mini-metrics row should include v2 signals (R², concentration) not stale RSI/CMF."""
        html = emailer._stock_card(1, _v2_pick(), "2026-05-15")
        # R² should appear as "0.92" somewhere (the cleanliness signal)
        assert "0.92" in html, "r2_log_60d missing from mini-metrics"
        # Concentration as "25" or "25.0"
        assert "25" in html
