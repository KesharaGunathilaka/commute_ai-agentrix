# SLR verified train data — blocked, not abandoned

**Date of investigation:** 2026-07-29
**Time spent:** ~20 minutes against a 45-minute time-box
**Outcome:** the source is unavailable. Nothing was ingested, and
`data/slr_schedules.json` has deliberately **not** been created.

## What was going to be built

Schedules and per-class fares for Colombo Fort ↔ Kandy and Colombo Fort ↔ Galle,
both directions, captured from the Sri Lanka Railways e-services portal into a
committed `data/slr_schedules.json`, so train legs could carry a genuine
`verified: true` with a citable government source and a capture date.

## Why it is blocked

The portal is switched off. Its own root page says so:

```
GET https://eservices.railway.gov.lk/          -> HTTP 200
<title>Offline</title>
"This Site temporarily offline due to system maintenance.
 The public will be notified once operations resume."
```

Everything under `/schedule/` returns 404, including the exact URL in the
specification:

```
GET /schedule/searchTrain.action?lang=en       -> HTTP 404  "Not Found"
GET /schedule/                                 -> HTTP 404
GET /schedule/index.action?lang=en             -> HTTP 404
GET /schedule/homeAction.action?lang=en        -> HTTP 404
```

Separately, the TLS certificate is expired:

```
subject    CN=eservices.railway.gov.lk
issuer     CN=E7, O=Let's Encrypt, C=US
not_before 2026-04-30 04:51:39 UTC
not_after  2026-07-29 04:51:38 UTC     <- expired the morning of the investigation
SAN        ['eservices.railway.gov.lk']
```

The certificate is the *correct* certificate for the host — right common name,
right SAN, real Let's Encrypt issuer. It simply lapsed, which is consistent
with the renewal cron being down for the same maintenance. Both symptoms point
at one planned outage rather than at anti-automation.

Rechecked at 16:31 UTC, ~12 hours after expiry: unchanged.

This is not a scraping problem. There is no session handling, CSRF token or
form-parameter discovery that gets past a maintenance page, so no further time
was spent. The observed form fields (Start Station, End Station, Start Time,
End Time, Search Date) could not be confirmed against the live page, and the
specification is explicit that parameter names must not be guessed.

## What was deliberately NOT done

**No `data/slr_schedules.json` was written.** Fabricating schedules and fares,
stamping them `source: "sri_lanka_railways"` and `verified: true`, and
committing them would be a worse version of R1: R1 at least substituted real
data from the wrong route, whereas invented data attributed to a government
source is simply a lie with a citation on it. An empty or partial file was
also rejected — a `verified: true` badge backed by nothing is worse than no
badge.

No ingestion script was committed either. An untested scraper written against
a page nobody has seen invites someone to run it and trust the output.

## What the system does instead, today

Exactly what Section 4's "corridor not covered" branch specifies, which is
already the behaviour since the R1 fix:

- Train legs keep their Google Maps times unchanged.
- `source: "google_maps"`, `verified: false`, `captured_date: null`.
- No fallback to any older train data, and no scraping in the request path.

So the uncovered-corridor half of the task is satisfied and verified. The
covered-corridor half is waiting on the source.

## To finish this when the portal returns

1. Confirm `https://eservices.railway.gov.lk/` no longer says "Offline" and the
   certificate verifies without `verify=False`.
2. `GET /schedule/searchTrain.action?lang=en` and read the real form: the
   `action` target, the method, and the exact input names. Do not guess them.
3. Write `scripts/ingest_slr.py` — offline, run by hand, output committed. It
   must fail loudly and leave any existing good file untouched rather than
   writing a partial one.
4. Confirm `data/slr_schedules.json` is **not** gitignored before committing.
   `.gitignore` currently excludes `data/chroma_db/` and `data/processed/`
   only, so a file at `data/slr_schedules.json` will be tracked — but check,
   because audit R5 is precisely the failure of assuming this.
5. Add the static Google-Maps-name → SLR-uppercase-name map for the stations on
   those two corridors only, hand-checked, resolved at ingestion time. No LLM
   in the request path.
6. Route SLR per-class fares through `fare_tool` so the uncertainty model still
   owns presentation, with a verified fare carrying no uncertainty band.

## Reproducing the finding

```
.venv/Scripts/python.exe -c "import requests,urllib3;urllib3.disable_warnings();\
r=requests.get('https://eservices.railway.gov.lk/',verify=False,timeout=20);\
print(r.status_code, 'Offline' in r.text)"
```
