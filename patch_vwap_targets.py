"""VWAP trades: one row per signal with T1 / T2 / T3 target columns (idempotent). Run on the VM.
VWAP opens 3 sub-positions per signal (signal_id suffixed -T1/-T2/-T3, each with its own target_price)."""
import os, shutil

D = os.path.expanduser("~/cognex-dashboard")


def edit(rel, pairs, marker):
    p = os.path.join(D, rel)
    s = open(p, encoding="utf-8").read()
    if marker in s:
        print("already patched:", rel)
        return
    for old, new in pairs:
        assert s.count(old) == 1, (rel, old[:60], s.count(old))
        s = s.replace(old, new)
    shutil.copy(p, p + ".bak-vwapT")
    open(p, "w", encoding="utf-8").write(s)
    print("patched:", rel)


# 1. backend: return signal_id / sl_price / target_price when the agent's trades table has them
edit("db_reader.py", [
    ('    where = " AND ".join(conditions)\n    return await _query(',
     '    where = " AND ".join(conditions)\n'
     '    _tc = {r["name"] for r in await _query(db_path, "PRAGMA table_info(trades)")}\n'
     '    _x = "".join(", " + c for c in ("signal_id", "sl_price", "target_price") if c in _tc)\n'
     '    return await _query('),
    ("status, strategy_used, mode, reason\n            FROM trades\n            WHERE {where}",
     "status, strategy_used, mode, reason{_x}\n            FROM trades\n            WHERE {where}"),
], "_x = ")

# 2. frontend
JS = r'''function setHead(v){const h=document.getElementById('tr-head');if(!h)return;if(!G.head0)G.head0=h.innerHTML;
  h.innerHTML=v?'<tr><th>Symbol</th><th>Direction</th><th>Strategy</th><th>Entry ₹</th><th>T1 ₹</th><th>T2 ₹</th><th>T3 ₹</th><th>Exit ₹ (T1 / T2 / T3)</th><th>Qty</th><th>P&L ₹</th><th>Status</th><th>Mode</th><th>Entry time</th><th>Exit time</th></tr>':G.head0;}
function renderVwap(trades){
  const g={},order=[];
  trades.forEach(t=>{
    const m=String(t.signal_id||'').match(/^(.*)-T([123])$/);
    const key=m?m[1]:('r'+t.id),leg=m?+m[2]:1;
    if(!g[key]){g[key]={legs:{},rows:[]};order.push(key);}
    g[key].rows.push(t);g[key].legs[leg]=t;
  });
  const f=v=>v?'₹'+Number(v).toFixed(2):'—';
  return order.map(k=>{
    const rows=g[k].rows,a=rows[0],L=n=>g[k].legs[n];
    const pnl=rows.reduce((s,t)=>s+(t.pnl_rs||0),0),qty=rows.reduce((s,t)=>s+(t.quantity||0),0);
    const open=rows.some(t=>(t.status||'').toUpperCase()==='OPEN');
    const st=open?'OPEN':(rows.every(t=>(t.status||'').toUpperCase()==='CLOSED')?'CLOSED':(a.status||'—'));
    const tc=n=>{const t=L(n);if(!t)return'<td>—</td>';const hit=t.exit_price&&String(t.reason||'').toUpperCase().includes('TARGET');return'<td style="color:#2563eb">'+f(t.target_price)+(hit?' ✓':'')+'</td>';};
    const ex=[1,2,3].map(n=>{const t=L(n);return t&&t.exit_price?Number(t.exit_price).toFixed(2):'—';}).join(' / ');
    const ps=pnl?(pnl>0?'+':'')+'₹'+Math.round(pnl).toLocaleString('en-IN'):'—';
    const pc=pnl>0?'cg':pnl<0?'cr':'cgr';
    const dir=(a.direction||'').toUpperCase();
    const xs=rows.map(t=>t.exit_time||'').filter(x=>x).sort().pop();
    const et=(a.entry_time||'').slice(0,16).replace('T',' '),xt=(!open&&xs)?xs.slice(0,16).replace('T',' '):'—';
    return '<tr><td class="ts3" style="font-size:11px">'+(a.symbol||'—').replace('NSE:','')+'</td>'
      +'<td class="t'+(dir==='BUY'?'bu':'se')+'">'+dir+'</td>'
      +'<td style="color:#64748b">'+(a.strategy_used||'—')+'</td>'
      +'<td>₹'+(a.entry_price||0).toFixed(2)+'</td>'+tc(1)+tc(2)+tc(3)
      +'<td>'+ex+'</td><td style="color:#94a3b8">'+qty+'</td><td class="'+pc+'">'+ps+'</td>'
      +'<td><span class="bge b'+(st[0]||'p').toLowerCase()+'">'+st+'</span></td>'
      +'<td><span class="bge bpa">'+(a.mode||'PAPER')+'</span></td>'
      +'<td style="color:#94a3b8;font-size:11px">'+et+'</td><td style="color:#94a3b8;font-size:11px">'+xt+'</td></tr>';
  }).join('');
}
'''

edit("static/index.html", [
    ("<thead><tr><th>Symbol</th>", '<thead id="tr-head"><tr><th>Symbol</th>'),
    ("body.innerHTML='<tr><td colspan=\"12\" class=\"es\">Loading...</td></tr>';",
     "body.innerHTML='<tr><td colspan=\"12\" class=\"es\">Loading...</td></tr>';setHead(G.tt==='vwap');"),
    ("if(!trades.length){body.innerHTML='<tr><td colspan=\"12\" class=\"es\">No trades found for this filter</td></tr>';return;}",
     "if(!trades.length){body.innerHTML='<tr><td colspan=\"12\" class=\"es\">No trades found for this filter</td></tr>';return;}\n"
     "    if(G.tt==='vwap'){body.innerHTML=renderVwap(trades);return;}"),
    ("function set(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}",
     JS + "function set(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}"),
], "function renderVwap(")
