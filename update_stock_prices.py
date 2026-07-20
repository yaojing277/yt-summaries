#!/usr/bin/env python3
"""更新股價 + 同步股價 + 更新所有分頁。

流程：
1. 向證交所（mis.twse.com.tw）抓取即時報價，失敗時改用 Yahoo Finance。
2. 寫入 stock_prices.json（canonical 資料）與 stock_data.js（供網頁離線顯示）。
3. 將股價列（#stock-ticker + 兩個 script 標籤）注入／更新到 index.html
   與所有摘要分頁，重複執行安全（以 HTML 註解標記為界）。

用法：python3 update_stock_prices.py
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAIPEI = timezone(timedelta(hours=8))

# 追蹤標的：依摘要庫內容選定（台股加權指數、台積電、三檔台股正二 ETF）
WATCHLIST = [
    {"symbol": "t00",    "yahoo": "^TWII",     "name": "加權指數"},
    {"symbol": "2330",   "yahoo": "2330.TW",   "name": "台積電"},
    {"symbol": "2454",   "yahoo": "2454.TW",   "name": "聯發科"},
    {"symbol": "6515",   "yahoo": "6515.TW",   "name": "穎崴"},
    {"symbol": "00631L", "yahoo": "00631L.TW", "name": "元大台灣50正2"},
    {"symbol": "00675L", "yahoo": "00675L.TW", "name": "富邦臺灣加權正2"},
    {"symbol": "00685L", "yahoo": "00685L.TW", "name": "群益臺灣加權正2"},
]

MARKER_START = "<!-- STOCK_TICKER_START -->"
MARKER_END = "<!-- STOCK_TICKER_END -->"
TICKER_BLOCK = (
    f"{MARKER_START}"
    '<div id="stock-ticker" class="stock-ticker"></div>'
    '<script src="stock_data.js"></script>'
    '<script src="stock_ticker.js"></script>'
    f"{MARKER_END}"
)


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_float(v):
    try:
        f = float(v)
        return f if f == f else None  # 排除 NaN
    except (TypeError, ValueError):
        return None


def fetch_twse():
    """證交所盤中即時報價（一次查詢全部標的）。"""
    ex_ch = "|".join(f"tse_{w['symbol']}.tw" for w in WATCHLIST)
    data = http_json(
        f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&json=1&delay=0"
    )
    by_sym = {m.get("c"): m for m in data.get("msgArray", [])}
    quotes = []
    for w in WATCHLIST:
        m = by_sym.get(w["symbol"])
        if not m:
            quotes.append(empty_quote(w))
            continue
        price = to_float(m.get("z"))
        if price is None:  # 無成交價時退回買賣報價中價，再退回昨收
            bid = to_float(str(m.get("b", "")).split("_")[0])
            ask = to_float(str(m.get("a", "")).split("_")[0])
            if bid is not None and ask is not None:
                price = (bid + ask) / 2
            else:
                price = bid or ask or to_float(m.get("y"))
        prev = to_float(m.get("y"))
        quotes.append(build_quote(w, price, prev))
    if all(q["price"] is None for q in quotes):
        raise RuntimeError("TWSE 回應中沒有任何有效報價")
    return quotes, "twse-mis"


def fetch_yahoo():
    """Yahoo Finance 備援（逐檔查詢）。"""
    quotes = []
    for w in WATCHLIST:
        try:
            data = http_json(
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{w['yahoo']}?interval=1d&range=5d"
            )
            meta = data["chart"]["result"][0]["meta"]
            price = to_float(meta.get("regularMarketPrice"))
            prev = to_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
            quotes.append(build_quote(w, price, prev))
        except Exception:
            quotes.append(empty_quote(w))
    if all(q["price"] is None for q in quotes):
        raise RuntimeError("Yahoo 回應中沒有任何有效報價")
    return quotes, "yahoo-finance"


def build_quote(w, price, prev):
    change = None if (price is None or prev is None) else round(price - prev, 4)
    return {
        "symbol": w["symbol"],
        "name": w["name"],
        "price": price,
        "prev_close": prev,
        "change": change,
        "change_pct": None if (change is None or not prev) else round(change / prev * 100, 2),
    }


def empty_quote(w):
    return build_quote(w, None, None)


def load_existing():
    path = ROOT / "stock_prices.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return None


def write_data(quotes, source, updated_at):
    payload = {"updated_at": updated_at, "source": source, "quotes": quotes}
    (ROOT / "stock_prices.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    js = "window.STOCK_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    (ROOT / "stock_data.js").write_text(js, encoding="utf-8")


def sync_pages():
    """把股價列注入所有 HTML 分頁；已存在則原地更新。"""
    changed = []
    block_re = re.compile(re.escape(MARKER_START) + ".*?" + re.escape(MARKER_END), re.S)
    for page in sorted(ROOT.glob("*.html")):
        html = page.read_text(encoding="utf-8")
        if MARKER_START in html:
            new_html = block_re.sub(TICKER_BLOCK, html)
        else:
            anchor = '<div class="wrap">'
            if anchor not in html:
                print(f"  ⚠ 跳過 {page.name}：找不到插入點 {anchor}")
                continue
            new_html = html.replace(anchor, anchor + "\n  " + TICKER_BLOCK, 1)
        if new_html != html:
            page.write_text(new_html, encoding="utf-8")
            changed.append(page.name)
    return changed


def main():
    quotes = None
    source = None
    for fetch in (fetch_twse, fetch_yahoo):
        try:
            quotes, source = fetch()
            break
        except Exception as e:
            print(f"  ⚠ {fetch.__name__} 失敗：{e}")

    if quotes is None:
        existing = load_existing()
        if existing and existing.get("quotes"):
            print("‼ 無法取得新報價，保留既有資料，僅同步分頁。")
            quotes = existing["quotes"]
            source = existing.get("source")
            updated_at = existing.get("updated_at")
        else:
            print("‼ 無法取得報價且無既有資料，先寫入空值（網頁端會自行抓即時報價）。")
            quotes = [empty_quote(w) for w in WATCHLIST]
            source = None
            updated_at = None
    else:
        updated_at = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")

    write_data(quotes, source, updated_at)
    print(f"✓ 股價資料已寫入 stock_prices.json / stock_data.js（來源：{source or '無'}）")

    changed = sync_pages()
    if changed:
        print(f"✓ 已更新 {len(changed)} 個分頁：{'、'.join(changed)}")
    else:
        print("✓ 所有分頁的股價列已是最新，無需變更。")

    for q in quotes:
        price = "—" if q["price"] is None else q["price"]
        print(f"  {q['name']}（{q['symbol']}）：{price}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
