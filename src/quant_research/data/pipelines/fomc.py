"""FOMC meeting / statement calendar from federalreserve.gov.
  2021+ : /monetarypolicy/fomccalendars.htm (includes scheduled future meetings)
  2016-2020 : /monetarypolicy/fomchistorical<YEAR>.htm
Output data/macro/fomc_meetings.parquet:
  year, meeting_label, month_text, date_text, meeting_start, meeting_end, statement_date, statement_url,
  has_press_conference, minutes_date (from 'Released <date>' text, 2021+), unscheduled, status (past/scheduled), sep (projection meeting '*')
statement_time_et: 14:00 ET for all meetings since 2013 (Fed practice); unscheduled/emergency actions
(e.g. 2020-03-03, 2020-03-15) were released at other times -> statement_time_et left null for those.
Knowledge time = statement_date 14:00 ET (scheduled meetings are announced >1 year ahead, so the DATE is known in advance)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pandas as pd
import requests

from quant_research.data.pipelines.common import DATA, log, update_manifest, write_parquet

H = {"User-Agent": "Mozilla/5.0 (cio-desk research)"}
MON = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
AB = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def mdate(y: int, mtxt: str, dtxt: str) -> tuple[dt.date | None, dt.date | None]:
    months = [AB.get(x[:3]) for x in re.split(r"[/-]", mtxt.strip())]
    days = [int(x) for x in re.findall(r"\d+", dtxt)]
    if not days or not months[0]:
        return None, None
    m0, m1 = months[0], months[-1] or months[0]
    start = dt.date(y, m0, days[0])
    end = dt.date(y, m1 if len(days) > 1 else m0, days[-1])
    return start, end


def current() -> list[dict[str, Any]]:
    s = requests.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", headers=H, timeout=60).text
    rows: list[dict[str, Any]] = []
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"<h4><a id=\"\d+\">(\d{4}) FOMC Meetings</a></h4>", s)]
    for k, (pos, y) in enumerate(heads):
        block = s[pos : heads[k + 1][0] if k + 1 < len(heads) else len(s)]
        for mt in re.finditer(
            r'fomc-meeting__month[^>]*><strong>([^<]+)</strong></div>\s*<div class="fomc-meeting__date[^>]*>([^<]+)</div>(.*?)(?=fomc-meeting__month|</div></div>\s*</div>\s*<div class="panel|$)',
            block,
            re.S,
        ):
            mtxt, dtxt, body = mt.group(1), mt.group(2).strip(), mt.group(3)
            st = re.search(r"monetary(\d{8})a\.htm", body)
            mins = re.search(r"Released ([A-Z][a-z]+ \d{1,2}, \d{4})", body)
            start, end = mdate(y, mtxt, dtxt)
            rows.append(
                dict(
                    year=y,
                    month_text=mtxt,
                    date_text=dtxt,
                    meeting_start=start,
                    meeting_end=end,
                    statement_date=dt.datetime.strptime(st.group(1), "%Y%m%d").date() if st else None,
                    statement_url=f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{st.group(1)}a.htm"
                    if st
                    else None,
                    has_press_conference="fomcpressconf" in body,
                    sep="*" in dtxt,
                    unscheduled="unscheduled" in (dtxt + body).lower() or "notation vote" in (dtxt + body).lower(),
                    minutes_date=pd.to_datetime(mins.group(1)).date() if mins else None,
                    source_page="fomccalendars",
                )
            )
    return rows


def historical(y: int) -> list[dict[str, Any]]:
    s = requests.get(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm", headers=H, timeout=60).text
    rows: list[dict[str, Any]] = []
    heads = list(re.finditer(r"<h5[^>]*>([^<]+)</h5>", s))
    for k, h in enumerate(heads):
        lab = h.group(1).strip()
        body = s[h.end() : heads[k + 1].start() if k + 1 < len(heads) else len(s)]
        m = re.match(r"([A-Za-z/]+)\s+([\d-]+)\s+(Meeting|\(unscheduled\)|Conference Call|.*?)\s*-\s*(\d{4})", lab)
        if not m:
            continue
        st = re.search(r"monetary(\d{8})a\.htm", body)
        start, end = mdate(y, m.group(1), m.group(2))
        rows.append(
            dict(
                year=y,
                month_text=m.group(1),
                date_text=m.group(2),
                meeting_label=lab,
                meeting_start=start,
                meeting_end=end,
                statement_date=dt.datetime.strptime(st.group(1), "%Y%m%d").date() if st else None,
                statement_url=f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{st.group(1)}a.htm"
                if st
                else None,
                has_press_conference="pressconf" in body,
                sep=None,
                unscheduled=("unscheduled" in lab.lower()) or ("conference call" in lab.lower()),
                minutes_date=None,
                source_page=f"fomchistorical{y}",
            )
        )
    return rows


def main() -> None:
    rows = current()
    for y in range(2016, 2021):
        rows += historical(y)
    df = pd.DataFrame(rows).sort_values(["meeting_start"]).reset_index(drop=True)
    today = dt.date.today()
    # regular (scheduled) FOMC meetings are two-day meetings; one-day entries are unscheduled calls/notation votes
    df["unscheduled"] = df["unscheduled"] | (df.meeting_start == df.meeting_end)
    df["status"] = [
        "past" if (d or e) and (d or e) <= today else "scheduled" for d, e in zip(df.statement_date, df.meeting_end)
    ]
    df["statement_time_et"] = ["14:00" if (not u and y >= 2013) else None for u, y in zip(df.unscheduled, df.year)]
    df["knowledge_time_utc"] = [
        pd.Timestamp(f"{d} {t}", tz="America/New_York").tz_convert("UTC")
        if pd.notna(d) and isinstance(t, str)
        else pd.NaT
        for d, t in zip(df.statement_date, df.statement_time_et)
    ]
    df["fetched_at_utc"] = pd.Timestamp.now(tz="UTC")
    write_parquet(df, DATA / "macro" / "fomc_meetings.parquet")
    info: dict[str, Any] = {
        "rows": len(df),
        "first": df.meeting_start.min(),
        "last": df.meeting_start.max(),
        "with_statement": int(df.statement_date.notna().sum()),
        "unscheduled": int(df.unscheduled.sum()),
        "scheduled_future": int((df.status == "scheduled").sum()),
    }
    update_manifest("fomc", info)
    log.info("%s", info)
    print(df[["year", "date_text", "meeting_start", "statement_date", "unscheduled", "status"]].to_string())


if __name__ == "__main__":
    main()
