#!/usr/bin/env python3
"""Fetch daily quotes from private GitHub Actions secret; publish only opaque IDs + prices."""
import json, urllib.request, urllib.parse, datetime, re, time, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
raw = os.environ.get("QUOTE_SYMBOLS_JSON", "")
if not raw:
    raise SystemExit("Missing GitHub Actions secret QUOTE_SYMBOLS_JSON")
try:
    SYMBOLS = json.loads(raw)
except Exception as exc:
    raise SystemExit("QUOTE_SYMBOLS_JSON is not valid JSON") from exc
if not isinstance(SYMBOLS, list) or not SYMBOLS:
    raise SystemExit("QUOTE_SYMBOLS_JSON must be a non-empty JSON array")

seen = set()
for item in SYMBOLS:
    if not isinstance(item, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(item.get("id", ""))):
        raise SystemExit("Each symbol needs a 32-character opaque id")
    if item["id"] in seen:
        raise SystemExit("Duplicate opaque id")
    seen.add(item["id"])

UA = "Mozilla/5.0 (compatible; PortfolioManagerDailyQuotes/1.1)"
def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

def fx_rates():
    xml = get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml").decode("utf-8")
    # ECB XML can use either single or double quotes. The previous parser
    # only accepted double quotes, which caused every non-EUR quote to fail.
    pairs = re.findall(
        r"""currency\s*=\s*['"]([A-Z]{3})['"]\s+rate\s*=\s*['"]([0-9.]+)['"]""",
        xml
    )
    rates = {"EUR": 1.0}
    for currency, rate in pairs:
        rates[currency] = float(rate)
    if len(rates) < 5:
        raise RuntimeError("ECB response parsed incorrectly: too few FX rates")
    return rates

def stooq_quote(symbol):
    if not symbol:
        return None
    end = datetime.date.today()
    start = end - datetime.timedelta(days=14)
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({
        "s": symbol.lower(), "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"), "i": "d"
    })
    try:
        lines = get(url).decode("utf-8", "replace").strip().splitlines()
        if len(lines) < 2 or lines[0].lower().startswith("no data"):
            return None
        headers = [value.strip().lower() for value in lines[0].split(",")]
        values = [value.strip() for value in lines[-1].split(",")]
        price = float(values[headers.index("close")])
        date = values[headers.index("date")]
        if price > 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            return price, date
    except Exception:
        return None
    return None

def yahoo_quote(symbol):
    if not symbol:
        return None
    try:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               + urllib.parse.quote(symbol, safe="") + "?range=5d&interval=1d")
        data = json.loads(get(url).decode("utf-8"))
        result = data["chart"]["result"][0]
        meta = result["meta"]
        closes = result["indicators"]["quote"][0]["close"]
        timestamps = result["timestamp"]
        for timestamp, close in reversed(list(zip(timestamps, closes))):
            if close and float(close) > 0:
                currency = meta.get("currency", "")
                date = datetime.datetime.fromtimestamp(
                    timestamp, datetime.timezone.utc
                ).date().isoformat()
                return float(close), date, currency
    except Exception:
        return None
    return None

def main():
    rates = fx_rates()
    quotes, failures = [], []
    for item in SYMBOLS:
        currency = (item.get("currency") or "").upper()
        source = ""
        quote = stooq_quote(item.get("stooq", ""))
        if quote:
            native_price, date = quote
            source = "Stooq"
        else:
            yahoo = yahoo_quote(item.get("yahoo", ""))
            if not yahoo:
                failures.append({"id": item["id"], "reason": "no quote"})
                continue
            native_price, date, yahoo_currency = yahoo
            currency = (yahoo_currency or currency).upper()
            source = "Yahoo Finance (unofficial chart endpoint)"

        if currency == "GBX":
            native_price /= 100
            currency = "GBP"
        if not currency:
            failures.append({"id": item["id"], "reason": "currency unknown"})
            continue
        if currency not in rates:
            failures.append({"id": item["id"], "reason": "FX unavailable"})
            continue

        fx_rate = rates[currency]  # units of foreign currency per 1 EUR
        price_eur = native_price / fx_rate
        quotes.append({
            "id": item["id"], "nativePrice": native_price,
            "currency": currency, "fxRate": fx_rate,
            "priceEur": round(price_eur, 8), "date": date, "source": source
        })
        time.sleep(0.12)

    payload = {
        "provider": "Stooq / Yahoo Finance + BCE",
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "quotes": quotes, "failed": failures,
        "coverage": {"symbols": len(SYMBOLS), "updated": len(quotes), "failed": len(failures)}
    }
    (ROOT / "prices.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Updated {len(quotes)} of {len(SYMBOLS)} private symbols; failures: {len(failures)}")

if __name__ == "__main__":
    main()
