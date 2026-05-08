"""
Tests for screener.indicator_helpers — covers post-audit fixes:
- Squeeze fire is direction-aware (bullish vs bearish)
- Tighter VCP detection criteria

(The OHLCV-based functions in indicators.py rely on pandas_ta/numba, which
won't install on every Python version. The pure-logic helpers tested here
are extracted into indicator_helpers.py for testability.)
"""
from __future__ import annotations

from screener.indicator_helpers import is_valid_vcp, squeeze_score


# ── Squeeze direction ─────────────────────────────────────────────────────────

class TestSqueezeScore:
    def test_bullish_fire_full_credit(self):
        s = squeeze_score(squeeze_on=False, squeeze_fired=True,
                          squeeze_bars=0, bullish_direction=True)
        assert s == 100.0

    def test_bearish_fire_partial_credit(self):
        """A bearish breakout from a squeeze should not score the same as bullish."""
        s = squeeze_score(squeeze_on=False, squeeze_fired=True,
                          squeeze_bars=0, bullish_direction=False)
        assert s < 50.0

    def test_long_bullish_squeeze_on_scores_high(self):
        s = squeeze_score(squeeze_on=True, squeeze_fired=False,
                          squeeze_bars=20, bullish_direction=True)
        assert s >= 60.0

    def test_long_bearish_squeeze_on_scores_lower(self):
        s_bull = squeeze_score(squeeze_on=True, squeeze_fired=False,
                               squeeze_bars=20, bullish_direction=True)
        s_bear = squeeze_score(squeeze_on=True, squeeze_fired=False,
                               squeeze_bars=20, bullish_direction=False)
        assert s_bear < s_bull

    def test_no_squeeze_zero(self):
        assert squeeze_score(squeeze_on=False, squeeze_fired=False,
                             squeeze_bars=0, bullish_direction=True) == 0.0


# ── VCP detection threshold ──────────────────────────────────────────────────

class TestIsValidVcp:
    def test_textbook_vcp_passes(self):
        # Strong score, multiple tightening contractions, 3 contractions total
        assert is_valid_vcp(vcp_score=65.0, tightening_count=2, n_contractions=3)

    def test_low_score_fails(self):
        assert not is_valid_vcp(vcp_score=45.0, tightening_count=2, n_contractions=3)

    def test_only_one_tightening_fails(self):
        """Old behaviour was tightening_count >= 1 — that's too lenient."""
        assert not is_valid_vcp(vcp_score=70.0, tightening_count=1, n_contractions=3)

    def test_too_many_contractions_fails(self):
        """A pattern with 9 contractions is noise, not a clean VCP."""
        assert not is_valid_vcp(vcp_score=70.0, tightening_count=4, n_contractions=9)

    def test_too_few_contractions_fails(self):
        assert not is_valid_vcp(vcp_score=70.0, tightening_count=1, n_contractions=1)
