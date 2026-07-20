/* 股價列元件：所有分頁共用。
   先顯示 stock_data.js 內建的基準報價，再嘗試向證交所抓即時報價更新。 */
(function () {
  var css = [
    '.stock-ticker{background:var(--card,#1a2232);border:1px solid var(--line,#2a3550);',
    'border-radius:14px;padding:12px 16px;margin-bottom:18px;display:flex;flex-wrap:wrap;',
    'gap:8px 22px;align-items:center;font-size:.88rem;}',
    '.stock-ticker .st-item{display:flex;gap:8px;align-items:baseline;white-space:nowrap;}',
    '.stock-ticker .st-name{color:var(--muted,#8b96ab);}',
    '.stock-ticker .st-price{font-variant-numeric:tabular-nums;font-weight:600;}',
    '.stock-ticker .st-chg{font-variant-numeric:tabular-nums;font-size:.82rem;}',
    '.stock-ticker .st-up{color:#ff6b6b;}',   /* 台股慣例：漲紅 */
    '.stock-ticker .st-down{color:#51cf66;}', /* 跌綠 */
    '.stock-ticker .st-flat{color:var(--muted,#8b96ab);}',
    '.stock-ticker .st-meta{margin-left:auto;color:var(--muted,#8b96ab);font-size:.75rem;}',
    '.stock-ticker .st-asof{color:var(--muted,#8b96ab);font-size:.72rem;}'
  ].join('');
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  function fmt(n, digits) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return Number(n).toLocaleString('zh-Hant', {
      minimumFractionDigits: digits, maximumFractionDigits: digits
    });
  }

  function render(data, liveNote) {
    var el = document.getElementById('stock-ticker');
    if (!el || !data || !data.quotes) return;
    var maxAsOf = data.quotes.reduce(function (m, q) {
      return (q.as_of && q.as_of > m) ? q.as_of : m;
    }, '');
    var html = data.quotes.map(function (q) {
      var digits = q.symbol === 't00' ? 0 : 2;
      var cls = 'st-flat', sign = '';
      if (q.change > 0) { cls = 'st-up'; sign = '▲'; }
      else if (q.change < 0) { cls = 'st-down'; sign = '▼'; }
      var chg = (q.change === null || q.change === undefined || isNaN(q.change))
        ? ''
        : '<span class="st-chg ' + cls + '">' + sign + fmt(Math.abs(q.change), digits) +
          ' (' + fmt(Math.abs(q.change_pct), 2) + '%)</span>';
      var stale = (q.as_of && maxAsOf && q.as_of < maxAsOf)
        ? '<span class="st-asof">(' + q.as_of.slice(5).replace('-', '/') + ')</span>'
        : '';
      return '<span class="st-item"><span class="st-name">' + q.name + '</span>' +
             '<span class="st-price ' + cls + '">' + fmt(q.price, digits) + '</span>' + chg + stale + '</span>';
    }).join('');
    var note = liveNote || (data.updated_at ? '更新於 ' + data.updated_at : '報價待更新');
    el.innerHTML = html + '<span class="st-meta">📈 ' + note + '</span>';
  }

  var base = (typeof window.STOCK_DATA === 'object' && window.STOCK_DATA) || { quotes: [] };
  render(base, null);

  // 證交所即時報價（盤中每 5 秒更新一次的公開介面）
  var exch = base.quotes.map(function (q) { return 'tse_' + q.symbol + '.tw'; }).join('|');
  if (!exch) return;
  var url = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=' + exch + '&json=1&delay=0';
  fetch(url).then(function (r) { return r.json(); }).then(function (j) {
    if (!j || !j.msgArray || !j.msgArray.length) return;
    var bySym = {};
    j.msgArray.forEach(function (m) { bySym[m.c] = m; });
    var t = '';
    var quotes = base.quotes.map(function (q) {
      var m = bySym[q.symbol];
      if (!m) return q;
      var price = parseFloat(m.z);
      if (isNaN(price)) {
        var bid = parseFloat(String(m.b || '').split('_')[0]);
        var ask = parseFloat(String(m.a || '').split('_')[0]);
        if (!isNaN(bid) && !isNaN(ask)) price = (bid + ask) / 2;
        else if (!isNaN(bid)) price = bid;
        else if (!isNaN(ask)) price = ask;
        else price = parseFloat(m.y);
      }
      var prev = parseFloat(m.y);
      if (isNaN(price)) return q;
      t = m.t || t;
      var change = isNaN(prev) ? null : price - prev;
      return {
        symbol: q.symbol, name: q.name, price: price,
        change: change,
        change_pct: (change === null || !prev) ? null : change / prev * 100
      };
    });
    render({ quotes: quotes }, '即時報價 ' + (t ? t.slice(0, 5) : ''));
  }).catch(function () { /* 離線或 CORS 受限時保留內建基準報價 */ });
})();
