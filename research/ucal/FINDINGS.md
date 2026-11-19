# U-CAL: DEV-window trading calendar

**Status:** accepted (data utility, not a strategy trial).
**Code:** `quant_research.data.pipelines.trading_calendar`; config `[datasets.trading-calendar]` in `configs/datasets.toml`.

## What it is
A fixed list of SPY/NYSE trading sessions for the development window (first session on or after
2007-01-01 through 2016-05-31). Strategy harnesses use it to make sure every date they touch is a real
session inside the development window, and never a date in the holdout period (2016-06-01 onward).

## Method
- **Build:** take the session dates of SPY daily bars, keep the ones inside the window, sort them and drop
  duplicates. Only the date column is read, and rows from the holdout period are filtered out when the file
  is read. The output is a one-column text file (`date`, then one ISO date per line).
- **Pin:** the file's SHA-256 fingerprint is recorded once and supplied at runtime through the environment
  (`QR_UCAL_SHA256`). It is not stored in the repo.
- **Check:** every call re-hashes the file and refuses it if the fingerprint differs. A request is refused
  as a whole if any date is unparseable, falls before the window, is on or after the holdout boundary, or is
  not a session in the calendar. Nothing is truncated or silently dropped.

## Result
- The rebuilt calendar has 2,369 sessions from 2007-01-03 to 2016-05-31 and contains no holdout dates.
- From 2008 onward it matches, date for date, the sessions in the desk's SPY options data, with no mismatches
  in either direction. The 2007 sessions predate the options data and were checked against the bar source only.
- An independent offline rebuild reproduced the original calendar file byte for byte.

## Tests
Synthetic calendars and bars only: valid sessions pass; weekends, holidays and other non-sessions are rejected;
dates before the window, on the holdout boundary and later are rejected; a tampered file fails the fingerprint
check; a missing pin fails closed; the build produces the expected sessions from synthetic bars.
