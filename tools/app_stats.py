#!/usr/bin/env python3
"""Report Kabar Unnie Mini App users and channel members.

App-user counts come from Google Analytics 4 property 565453562
(measurement ID G-SYRMSWQCHQ). This script prints the exact GA4 Data API
(and MCP connector) queries. If Application Default Credentials can reach
the Analytics Data API, it also runs them and prints the numbers.

Channel members come from Telegram Bot API getChatMemberCount. The token
is read from KABARUNNIE_BOT_TOKEN and is never printed.

Usage:
  python3 tools/app_stats.py
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PROPERTY = "properties/565453562"
MEASUREMENT_ID = "G-SYRMSWQCHQ"
CHANNEL = "@kabarunnie"
WIB = timezone(timedelta(hours=7))

# Realtime on standard GA4 covers the last 30 minutes (not 60).
REALTIME_REQUEST = {
    "metrics": [
        {"name": "activeUsers"},
        {"name": "eventCount"},
    ],
    "minuteRanges": [{"name": "last_30m", "startMinutesAgo": 29, "endMinutesAgo": 0}],
}

TODAY_REQUEST = {
    "dateRanges": [{"startDate": "today", "endDate": "today"}],
    "dimensions": [{"name": "hour"}],
    "metrics": [
        {"name": "activeUsers"},
        {"name": "eventCount"},
    ],
    "orderBys": [{"dimension": {"dimensionName": "hour"}}],
}

TOTAL_REQUEST = {
    "dateRanges": [{"startDate": "2026-11-23", "endDate": "today"}],
    "metrics": [
        {"name": "activeUsers"},
        {"name": "totalUsers"},
    ],
}

MCP_HINTS = f"""
GA4 MCP (namespace user-Google-analytics)
  property: {PROPERTY}

  Active users, last 30 min (standard GA4 realtime window):
    run_realtime_report
    request: {json.dumps(REALTIME_REQUEST, ensure_ascii=False)}

  Today's users, by hour (Asia/Jakarta):
    run_report  action=report
    request: {json.dumps(TODAY_REQUEST, ensure_ascii=False)}
    Sum activeUsers across hours is not unique-for-the-day; use the same
    request without the hour dimension for today's unique users:
    {{"dateRanges":[{{"startDate":"today","endDate":"today"}}],
      "metrics":[{{"name":"activeUsers"}},{{"name":"totalUsers"}}]}}

  All-time users (since property creation, 23 Nov 2026):
    run_report  action=report
    request: {json.dumps(TOTAL_REQUEST, ensure_ascii=False)}
""".strip()


def _redact(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "<redacted>")


def channel_members() -> tuple[int | None, str | None]:
    token = os.environ.get("KABARUNNIE_BOT_TOKEN", "").strip()
    if not token:
        return None, "KABARUNNIE_BOT_TOKEN is not set"
    url = (
        "https://api.telegram.org/bot"
        + token
        + "/getChatMemberCount?"
        + urllib.parse.urlencode({"chat_id": CHANNEL})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "KabarUnnie-app-stats/1.0"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return None, _redact(f"HTTP {exc.code}: {raw}", token)
    except Exception as exc:  # noqa: BLE001 — surface a clean, redacted error
        return None, _redact(str(exc), token)
    if not body.get("ok"):
        return None, _redact(json.dumps(body, ensure_ascii=False), token)
    return int(body["result"]), None


def _metric_map(response: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    names = [h.get("name") for h in response.get("metricHeaders") or []]
    rows = response.get("rows") or []
    if not rows or not names:
        for name in names:
            out[name] = 0
        return out
    values = rows[0].get("metricValues") or []
    for i, name in enumerate(names):
        try:
            out[name] = int(float(values[i].get("value") or 0))
        except (TypeError, ValueError, IndexError):
            out[name] = 0
    return out


def _hourly_rows(response: dict) -> list[dict]:
    rows = []
    names = [h.get("name") for h in response.get("metricHeaders") or []]
    for row in response.get("rows") or []:
        dim = (row.get("dimensionValues") or [{}])[0].get("value") or ""
        metrics = {}
        values = row.get("metricValues") or []
        for i, name in enumerate(names):
            try:
                metrics[name] = int(float(values[i].get("value") or 0))
            except (TypeError, ValueError, IndexError):
                metrics[name] = 0
        rows.append({"hour": dim, **metrics})
    return rows


def run_ga() -> dict | None:
    """Run reports when Google ADC + analyticsdata are available."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            MinuteRange,
            OrderBy,
            RunRealtimeReportRequest,
            RunReportRequest,
        )
    except ImportError:
        return None

    try:
        client = BetaAnalyticsDataClient()
        rt = client.run_realtime_report(
            RunRealtimeReportRequest(
                property=PROPERTY,
                metrics=[Metric(name="activeUsers"), Metric(name="eventCount")],
                minute_ranges=[
                    MinuteRange(name="last_30m", start_minutes_ago=29, end_minutes_ago=0)
                ],
            )
        )
        today = client.run_report(
            RunReportRequest(
                property=PROPERTY,
                date_ranges=[DateRange(start_date="today", end_date="today")],
                metrics=[Metric(name="activeUsers"), Metric(name="totalUsers")],
            )
        )
        hourly = client.run_report(
            RunReportRequest(
                property=PROPERTY,
                date_ranges=[DateRange(start_date="today", end_date="today")],
                dimensions=[Dimension(name="hour")],
                metrics=[Metric(name="activeUsers"), Metric(name="eventCount")],
                order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="hour"))],
            )
        )
        total = client.run_report(
            RunReportRequest(
                property=PROPERTY,
                date_ranges=[DateRange(start_date="2026-11-23", end_date="today")],
                metrics=[Metric(name="activeUsers"), Metric(name="totalUsers")],
            )
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    def as_dict(resp) -> dict:
        return json.loads(type(resp).to_json(resp))

    return {
        "last_30m": _metric_map(as_dict(rt)),
        "today": _metric_map(as_dict(today)),
        "today_by_hour": _hourly_rows(as_dict(hourly)),
        "total": _metric_map(as_dict(total)),
    }


def main() -> int:
    now = datetime.now(WIB).strftime("%Y-%m-%d %H:%M %Z")
    print(f"Kabar Unnie stats  ({now})")
    print(f"GA4 property {PROPERTY}   measurement {MEASUREMENT_ID}")
    print()

    members, err = channel_members()
    if err:
        print(f"Channel {CHANNEL} members: unavailable ({err})")
    else:
        print(f"Channel {CHANNEL} members: {members}")

    ga = run_ga()
    if not ga:
        print("GA4 numbers: not fetched here (no Analytics Data API credentials).")
        print("Use the MCP queries below, or set up Application Default Credentials.")
    elif "error" in ga:
        print(f"GA4 numbers: not fetched ({ga['error']})")
    else:
        last = ga["last_30m"]
        today = ga["today"]
        total = ga["total"]
        print(
            f"Active users last 30 min (GA4 realtime window): "
            f"{last.get('activeUsers', 0)}"
        )
        print(f"Today's users: {today.get('activeUsers', today.get('totalUsers', 0))}")
        print(f"Total users: {total.get('totalUsers', total.get('activeUsers', 0))}")
        if ga["today_by_hour"]:
            print("Today by hour (WIB):")
            for row in ga["today_by_hour"]:
                print(
                    f"  {row['hour']}:00  users={row.get('activeUsers', 0)}  "
                    f"events={row.get('eventCount', 0)}"
                )

    print()
    print(MCP_HINTS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
