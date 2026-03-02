"""
Build and send the daily HTML email.

Chart images are referenced via raw.githubusercontent.com URLs (public repo).
Charts must already be committed to the repo before this function is called.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from . import config

logger = logging.getLogger(__name__)


# ── HTML template helpers ─────────────────────────────────────────────────────

def _score_color(score: float) -> str:
    if score >= 75:
        return "#26a641"
    if score >= 60:
        return "#e3b341"
    return "#6e7681"


def _bar(pct: float, color: str, label: str) -> str:
    """Render a mini progress bar as an HTML table row."""
    pct = max(0.0, min(100.0, pct))
    return f"""
      <tr>
        <td style="color:#8b949e;font-size:10px;padding:1px 6px 1px 0;white-space:nowrap;">{label}</td>
        <td style="width:120px;background:#21262d;border-radius:3px;height:8px;vertical-align:middle;">
          <div style="width:{pct:.0f}%;background:{color};border-radius:3px;height:8px;"></div>
        </td>
        <td style="color:#c9d1d9;font-size:10px;padding-left:5px;">{pct:.0f}</td>
      </tr>"""


def _metric(label: str, value: str) -> str:
    return f"""
      <td style="text-align:center;padding:4px 8px;">
        <div style="color:#8b949e;font-size:9px;text-transform:uppercase;">{label}</div>
        <div style="color:#c9d1d9;font-size:12px;font-weight:bold;">{value}</div>
      </td>"""


def _stage2_badge(is_stage2: bool) -> str:
    if is_stage2:
        return '<span style="background:#1a4731;color:#26a641;border:1px solid #26a641;border-radius:12px;padding:2px 8px;font-size:10px;font-weight:bold;">Stage 2</span>'
    return '<span style="background:#2d2208;color:#e3b341;border:1px solid #e3b341;border-radius:12px;padding:2px 8px;font-size:10px;">Near Stage 2</span>'


def _stock_card(rank: int, pick: dict[str, Any], run_date: str) -> str:
    ticker        = pick["ticker"]
    company       = pick.get("company_name", ticker)
    sector        = pick.get("sector", "Unknown")
    close         = pick.get("close", 0.0)
    change_pct    = pick.get("change_pct", 0.0)
    score         = pick.get("composite_score", 0.0)
    trend_s       = pick.get("trend_score", 0.0)
    rs_s          = pick.get("rs_score", 0.0)
    vol_s         = pick.get("volume_score", 0.0)
    mom_s         = pick.get("momentum_score", 0.0)
    stage2_s      = pick.get("stage2_score", 0.0)
    rs_pct        = pick.get("rs_3m_percentile", 0.0)
    adx           = pick.get("adx_14", 0.0)
    rsi           = pick.get("rsi_14", 50.0)
    cmf           = pick.get("cmf_20", 0.0)
    obv_trend     = pick.get("obv_trend", "flat").capitalize()
    dist_high     = pick.get("dist_from_52w_high_pct", 0.0)
    is_stage2     = pick.get("stage2_score", 0.0) == 100.0
    change_color  = "#26a641" if change_pct >= 0 else "#da3633"
    change_arrow  = "▲" if change_pct >= 0 else "▼"

    chart_url = f"{config.GITHUB_RAW_BASE}/results/charts/{ticker}_{run_date}.png"

    return f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;margin:12px 0;padding:16px;max-width:680px;">
      <!-- Header -->
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
        <div>
          <span style="color:#8b949e;font-size:12px;margin-right:6px;">#{rank}</span>
          <span style="color:#58a6ff;font-size:22px;font-weight:bold;">{ticker}</span>
          <span style="color:#8b949e;font-size:12px;margin-left:8px;">{company}</span>
          <br/>
          <span style="color:#6e7681;font-size:10px;">{sector}</span>
          &nbsp;&nbsp;{_stage2_badge(is_stage2)}
        </div>
        <div style="text-align:right;">
          <div style="font-size:22px;font-weight:bold;color:#c9d1d9;">${close:.2f}</div>
          <div style="font-size:12px;color:{change_color};">{change_arrow} {abs(change_pct):.2f}%</div>
          <div style="margin-top:4px;font-size:20px;font-weight:bold;color:{_score_color(score)};">{score:.1f}<span style="font-size:10px;color:#6e7681;"> /100</span></div>
        </div>
      </div>

      <!-- Score bars -->
      <table style="border-collapse:collapse;margin-bottom:10px;">
        {_bar(trend_s,  "#238636", "Trend")}
        {_bar(rs_s,     "#58a6ff", "Rel. Strength")}
        {_bar(vol_s,    "#bc8cff", "Volume")}
        {_bar(mom_s,    "#e3b341", "Momentum")}
        {_bar(stage2_s, "#26a641", "Stage 2")}
      </table>

      <!-- Key metrics -->
      <table style="border-collapse:collapse;background:#0d1117;border-radius:6px;width:100%;margin-bottom:12px;">
        <tr>
          {_metric("RS %ile", f"{rs_pct:.0f}")}
          {_metric("ADX", f"{adx:.1f}")}
          {_metric("RSI 14", f"{rsi:.1f}")}
          {_metric("CMF", f"{cmf:+.2f}")}
          {_metric("OBV", obv_trend)}
          {_metric("vs 52W Hi", f"{dist_high:.1f}%")}
        </tr>
      </table>

      <!-- Chart -->
      <div>
        <img src="{chart_url}"
             alt="{ticker} technical chart"
             style="width:100%;max-width:680px;border-radius:6px;border:1px solid #30363d;"
             onerror="this.style.display='none'"/>
      </div>
    </div>"""


def build_html(
    top_picks: list[dict[str, Any]],
    run_date: str,
    stats: dict[str, Any],
) -> str:
    """Render the full HTML email."""
    screened    = stats.get("screened_count", 0)
    qualifying  = stats.get("qualifying_count", 0)
    n_picks     = len(top_picks)
    now_str     = datetime.now().strftime("%A, %B %-d %Y")

    cards = "\n".join(
        _stock_card(i + 1, pick, run_date) for i, pick in enumerate(top_picks)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Russell 2000 Technical Screen — {run_date}</title>
</head>
<body style="margin:0;padding:0;background:#0d1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#c9d1d9;">

  <!-- Header -->
  <div style="background:#161b22;border-bottom:1px solid #30363d;padding:20px 24px;">
    <div style="max-width:700px;margin:0 auto;">
      <div style="font-size:20px;font-weight:bold;color:#c9d1d9;">Russell 2000 Technical Screen</div>
      <div style="color:#8b949e;font-size:13px;margin-top:4px;">{now_str}</div>
      <div style="margin-top:12px;display:inline-flex;gap:20px;">
        <div style="color:#8b949e;font-size:12px;">Screened <strong style="color:#c9d1d9;">{screened:,}</strong></div>
        <div style="color:#8b949e;font-size:12px;">Qualifying <strong style="color:#26a641;">{qualifying:,}</strong></div>
        <div style="color:#8b949e;font-size:12px;">Top Picks <strong style="color:#58a6ff;">{n_picks}</strong></div>
      </div>
    </div>
  </div>

  <!-- Score legend -->
  <div style="background:#0d1117;padding:12px 24px;border-bottom:1px solid #21262d;">
    <div style="max-width:700px;margin:0 auto;font-size:10px;color:#6e7681;">
      Scoring: &nbsp;
      <span style="color:#238636;">Trend 35%</span> &nbsp;|&nbsp;
      <span style="color:#58a6ff;">Relative Strength 25%</span> &nbsp;|&nbsp;
      <span style="color:#bc8cff;">Volume/Accum 20%</span> &nbsp;|&nbsp;
      <span style="color:#e3b341;">Momentum 15%</span> &nbsp;|&nbsp;
      <span style="color:#26a641;">Stage 2 5%</span>
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Hard filters: Price &gt; $2, Volume &gt; 100k, Close &gt; EMA 200, EMA 200 slope positive
    </div>
  </div>

  <!-- Stock cards -->
  <div style="max-width:700px;margin:0 auto;padding:16px 24px;">
    {cards}
  </div>

  <!-- Footer -->
  <div style="background:#161b22;border-top:1px solid #30363d;padding:16px 24px;margin-top:20px;">
    <div style="max-width:700px;margin:0 auto;font-size:10px;color:#6e7681;line-height:1.6;">
      <a href="{config.DASHBOARD_URL}" style="color:#58a6ff;text-decoration:none;">View full dashboard →</a>
      &nbsp;&nbsp;·&nbsp;&nbsp;
      This is not investment advice. All screening is based on technical analysis only.
      Past patterns do not guarantee future performance. Do your own research.
    </div>
  </div>

</body>
</html>"""


# ── Send ──────────────────────────────────────────────────────────────────────

def send_email(
    top_picks: list[dict[str, Any]],
    run_date: str,
    stats: dict[str, Any],
) -> None:
    """Build and send the daily email via Gmail SMTP."""
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not set — skipping email send")
        return
    if not config.EMAIL_RECIPIENTS:
        logger.warning("No email recipients configured — skipping")
        return

    html = build_html(top_picks, run_date, stats)
    n = len(top_picks)
    subject = f"Stock Screen: {run_date} | Top {n} Russell 2000 Setups"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config.GMAIL_USER
    msg["To"]      = ", ".join(config.EMAIL_RECIPIENTS)
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        server.sendmail(config.GMAIL_USER, config.EMAIL_RECIPIENTS, msg.as_string())

    logger.info(
        "Email sent to %d recipient(s): %s",
        len(config.EMAIL_RECIPIENTS),
        subject,
    )
