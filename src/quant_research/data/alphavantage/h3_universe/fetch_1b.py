#!/usr/bin/env python3
"""H3 Stage 1b: TIME_SERIES_DAILY_ADJUSTED full JSON for FETCH_LIST_1b.txt[START:END] (ELIGIBLE_SCAN minus 4 symbols with chars unusable as filenames, pending Victor ruling). One fresh process per chunk.
Key from env only. <=60/min (>=1.05s between call starts). 1 retry on network exception only.
Body classes: ok (has 'Time Series (Daily)'), error_message, empty -> logged, continue (no_series candidates);
Note/Information/throttle text -> STOP exit 3. Exits: 0 ok, 2 no key, 3 throttle, 4 >5 network failures, 5 target exists, 6 bad args, 7 exception (type only)."""
import os, sys, time, urllib.request, urllib.parse, hashlib, datetime
def cls(b):
    if b"Time Series (Daily)" in b[:2000]: return "ok"
    if len(b.strip())<=2: return "empty"
    h=b[:4000]
    if b"Error Message" in h: return "error_message"
    if b"Note" in h or b"Information" in h or b"rate limit" in h.lower() or b"premium" in h.lower(): return "throttle"
    return "unknown"
def main():
    try: s,e=int(sys.argv[1]),int(sys.argv[2])
    except Exception: print("BAD_ARGS"); return 6
    k=os.environ.get("ALPHAVANTAGE_API_KEY")
    if not k: print("NO_KEY"); return 2
    syms=open("FETCH_LIST_1b.txt").read().split()[s:e]
    for x in syms:
        if os.path.exists(f"raw/1b/{x}.json"): print("EXISTS",x); return 5
    log=open(f"CALLS_1b_{s:05d}_{e:05d}.log","x"); fails=0; last=0.0
    cnt={}
    for x in syms:
        url="https://www.alphavantage.co/query?"+urllib.parse.urlencode({"function":"TIME_SERIES_DAILY_ADJUSTED","symbol":x,"outputsize":"full","datatype":"json"})+"&apikey="+k
        b=None
        for att in (1,2):
            w=last+1.05-time.time()
            if w>0: time.sleep(w)
            last=time.time()
            try: b=urllib.request.urlopen(url,timeout=90).read(); break
            except Exception as ex:
                fails+=1; log.write(f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\t{x}\tattempt{att}\tNETERR\t{type(ex).__name__}\n"); log.flush()
                if fails>5: print("TOO_MANY_FAILURES"); return 4
        if b is None: c="neterr"; h="-"; nb=0
        else:
            c=cls(b); h=hashlib.sha256(b).hexdigest(); nb=len(b)
            fd=os.open(f"raw/1b/{x}.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444); os.write(fd,b); os.close(fd)
        cnt[c]=cnt.get(c,0)+1
        log.write(f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\t{x}\t{c}\tbytes={nb}\t{h}\n"); log.flush()
        if c=="throttle": print("THROTTLE_STOP at",x); return 3
    print("DONE",s,e,cnt); return 0
if __name__=="__main__":
    try: sys.exit(main())
    except SystemExit: raise
    except Exception as ex: print("EXC",type(ex).__name__); sys.exit(7)
