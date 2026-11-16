#!/usr/bin/env python3
import json, urllib.request, urllib.parse, datetime, re, time, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
raw=os.environ.get("QUOTE_SYMBOLS_JSON","")
if not raw: raise SystemExit("Missing required GitHub Actions secret QUOTE_SYMBOLS_JSON")
try: SYMBOLS=json.loads(raw)
except Exception as exc: raise SystemExit("QUOTE_SYMBOLS_JSON is not valid JSON") from exc
if not isinstance(SYMBOLS,list) or not SYMBOLS: raise SystemExit("QUOTE_SYMBOLS_JSON must be a non-empty JSON array")
seen=set()
for item in SYMBOLS:
 if not isinstance(item,dict) or not re.fullmatch(r"[a-f0-9]{32}",str(item.get("id",""))): raise SystemExit("Each private symbol must contain a 32-character opaque id")
 if item["id"] in seen: raise SystemExit("Duplicate opaque id")
 seen.add(item["id"])
UA="Mozilla/5.0 (compatible; PortfolioManagerDailyQuotes/1.0)"
def get(url,timeout=25):
 req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
 with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()
def fx_rates():
 xml=get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml").decode("utf-8"); rates={"EUR":1.0}
 for c,v in re.findall(r'currency="([A-Z]{3})"\s+rate="([0-9.]+)"',xml):rates[c]=float(v)
 return rates
def stooq_quote(sym):
 if not sym:return None
 end=datetime.date.today(); start=end-datetime.timedelta(days=14)
 url="https://stooq.com/q/d/l/?"+urllib.parse.urlencode({"s":sym.lower(),"d1":start.strftime("%Y%m%d"),"d2":end.strftime("%Y%m%d"),"i":"d"})
 try:
  lines=get(url).decode("utf-8","replace").strip().splitlines()
  if len(lines)<2 or lines[0].lower().startswith("no data"):return None
  h=[x.strip().lower() for x in lines[0].split(",")]; vals=[x.strip() for x in lines[-1].split(",")]; q=float(vals[h.index("close")]); d=vals[h.index("date")]
  if q>0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}",d):return q,d
 except Exception:return None
 return None
def yahoo_quote(sym):
 if not sym:return None
 try:
  url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(sym,safe="")+"?range=5d&interval=1d"
  data=json.loads(get(url).decode()); result=data["chart"]["result"][0]; meta=result["meta"]; closes=result["indicators"]["quote"][0]["close"]; stamps=result["timestamp"]
  for ts,cl in reversed(list(zip(stamps,closes))):
   if cl and float(cl)>0:return float(cl),datetime.datetime.fromtimestamp(ts,datetime.timezone.utc).date().isoformat(),meta.get("currency","")
 except Exception:return None
 return None
def main():
 rates=fx_rates(); quotes=[]; failures=[]
 for item in SYMBOLS:
  currency=item.get("currency") or ""; source=""; sq=stooq_quote(item.get("stooq",""))
  if sq:native,date=sq;source="Stooq"
  else:
   yq=yahoo_quote(item.get("yahoo",""))
   if not yq:failures.append({"id":item["id"],"reason":"no quote"});continue
   native,date,ycur=yq;currency=ycur or currency;source="Yahoo Finance (unofficial chart endpoint)"
  if not currency:failures.append({"id":item["id"],"reason":"currency unknown"});continue
  if currency=="GBX":native/=100;currency="GBP"
  if currency not in rates:failures.append({"id":item["id"],"reason":"FX unavailable"});continue
  quotes.append({"id":item["id"],"nativePrice":native,"currency":currency,"fxRate":rates[currency],"priceEur":round(native/rates[currency],8),"date":date,"source":source});time.sleep(.12)
 payload={"provider":"Stooq / Yahoo Finance + BCE","updatedAt":datetime.datetime.now(datetime.timezone.utc).isoformat(),"quotes":quotes,"failed":failures,"coverage":{"symbols":len(SYMBOLS),"updated":len(quotes),"failed":len(failures)}}
 (ROOT/"prices.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
 print(f"Updated {len(quotes)} of {len(SYMBOLS)} private symbols; public output contains opaque IDs only.")
if __name__=="__main__":main()
