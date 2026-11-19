#!/bin/bash
# Download SEC "Insider Transactions Data Sets" (Forms 3/4/5) quarterly zips.
# SEC fair access: declared User-Agent with contact, 1 request at a time (<<10 req/s).
UA="CIO-desk research (paper trading desk) research-contact@example.com"
mkdir -p raw
for y in $(seq ${1:-2012} ${2:-2026}); do for q in 1 2 3 4; do
  f=raw/${y}q${q}_form345.zip; [ -s $f ] && continue
  url=https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/${y}q${q}_form345.zip
  code=$(curl -s -A "$UA" -o $f.part -w '%{http_code}' $url)
  # SEC serves recent quarters (2026q2+) from /files/datastandardsinnovation/... ; try that path too
  [ "$code" = 200 ] || { sleep 1; code=$(curl -s -A "$UA" -o $f.part -w '%{http_code}' ${url/structureddata/datastandardsinnovation}); }
  if [ "$code" = 200 ]; then mv $f.part $f; echo "$f ok $(stat -c%s $f)"; else rm -f $f.part; echo "$f HTTP $code"; fi
  sleep 1
done; done
