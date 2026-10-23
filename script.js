const CATS={expense:["Food","Transport","Rent","Bills","Shopping","Health","Fun","Other"],income:["Salary","Freelance","Gift","Other"]};
const KEY="expense-tracker-v1";
let tx=[],type="expense",month="all",tab=1,editId=null,budgets={};
try{tx=JSON.parse(localStorage.getItem(KEY)||"[]")}catch(e){tx=[]}
try{budgets=JSON.parse(localStorage.getItem(KEY+"-b")||"{}")}catch(e){budgets={}}
const $=id=>document.getElementById(id);
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(tx));localStorage.setItem(KEY+"-b",JSON.stringify(budgets))}catch(e){}};
const fmt=n=>n.toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const mlabel=m=>new Date(m+"-01T00:00").toLocaleDateString("en-IN",{month:"short",year:"numeric"});
const sum=(a,t)=>a.filter(x=>x.type===t).reduce((s,x)=>s+x.amt,0);

function setCats(sel){$("cat").innerHTML=CATS[type].map(c=>`<option>${c}</option>`).join("");if(sel)$("cat").value=sel;if(!$("fcat").options.length)$("fcat").innerHTML='<option value="all">All categories</option>'+[...new Set([...CATS.expense,...CATS.income])].map(c=>`<option>${c}</option>`).join("")}
function setMonths(){
  const ms=[...new Set(tx.map(x=>x.date.slice(0,7)))].sort().reverse();
  if(month!=="all"&&!ms.includes(month))month="all";
  $("month").innerHTML='<option value="all">All time</option>'+ms.map(m=>`<option value="${m}"${m===month?" selected":""}>${mlabel(m)}</option>`).join("");
}
function render(){
  setMonths();
  const cur=tx.filter(x=>month==="all"||x.date.startsWith(month)).sort((a,b)=>b.date.localeCompare(a.date)||b.id-a.id);
  const i=sum(cur,"income"),e=sum(cur,"expense");
  $("inc").textContent="₹"+fmt(i);$("sr").textContent=i>0?Math.round((i-e)/i*100)+"%":"–";$("exp").textContent="₹"+fmt(e);
  $("bal").textContent=(i-e<0?"−":"")+"₹"+fmt(Math.abs(i-e));
  const q=$("q").value.toLowerCase(),ft=$("ftype").value,fc=$("fcat").value;
  const vis=cur.filter(x=>(ft==="all"||x.type===ft)&&(fc==="all"||x.cat===fc)&&(!q||(x.cat+" "+x.note).toLowerCase().includes(q)));
  $("list").innerHTML=vis.length?vis.map(x=>`<li class="row"><div class="mid"><b>${esc(x.cat)}</b><span>${x.date}${x.note?" — "+esc(x.note):""}</span></div><div class="amt ${x.type==="income"?"inc":"exp"}">${x.type==="income"?"+":"−"}₹${fmt(x.amt)}</div><button class="edit" data-id="${x.id}">Edit</button><button class="del" data-id="${x.id}" aria-label="Delete transaction">×</button></li>`).join(""):
    `<div class="empty">${tx.length?'No matching transactions.':'No transactions yet. Add one above.<br><button id="demo">Load sample data</button>'}</div>`;
  renderBuds();
  // reports
  const byM={};tx.forEach(x=>{const m=x.date.slice(0,7);(byM[m]=byM[m]||{income:0,expense:0})[x.type]+=x.amt});
  const ms=Object.keys(byM).sort().slice(-6);
  if(!ms.length){$("chart").innerHTML='<div class="empty">Add transactions to see your monthly report.</div>'}
  else{
    const max=Math.max(...ms.flatMap(m=>[byM[m].income,byM[m].expense]),1),H=160,bw=18,gap=34,W=ms.length*(bw*2+gap)+20;
    $("chart").innerHTML=`<svg viewBox="0 0 ${W} ${H+30}" width="${Math.max(W,300)}" height="${H+30}" role="img" aria-label="Monthly income and expenses">`+
    ms.map((m,k)=>{const x=10+k*(bw*2+gap),hi=byM[m].income/max*H,he=byM[m].expense/max*H;
      return `<rect x="${x}" y="${H-hi}" width="${bw}" height="${hi}" rx="3" fill="var(--inc)"/><rect x="${x+bw+2}" y="${H-he}" width="${bw}" height="${he}" rx="3" fill="var(--exp)"/><text x="${x+bw}" y="${H+18}" text-anchor="middle" font-size="11" fill="var(--muted)">${mlabel(m).split(" ")[0]}</text>`}).join("")+`</svg>`;
  }
  const ex=cur.filter(x=>x.type==="expense"),tot=sum(ex,"expense"),bc={};
  ex.forEach(x=>bc[x.cat]=(bc[x.cat]||0)+x.amt);
  const rows=Object.entries(bc).sort((a,b)=>b[1]-a[1]);
  $("cats").innerHTML=rows.length?rows.map(([c,v])=>`<div class="bar"><span>${c}</span><div class="track"><div class="fill" style="width:${v/tot*100}%"></div></div><span style="text-align:right">₹${fmt(v)}</span></div>`).join("")+`<p class="empty" style="padding:8px 0 0">Biggest category: ${rows[0][0]} (${Math.round(rows[0][1]/tot*100)}% of spending)</p>`:'<div class="empty">No expenses in this period.</div>';
}
function renderBuds(){
  const p=n=>String(n).padStart(2,"0"),d=new Date(),bm=month==="all"?`${d.getFullYear()}-${p(d.getMonth()+1)}`:month;
  $("budh").textContent="Budgets for "+mlabel(bm);
  $("buds").innerHTML=CATS.expense.map(c=>{
    const sp=tx.filter(x=>x.type==="expense"&&x.cat===c&&x.date.startsWith(bm)).reduce((s,x)=>s+x.amt,0),lim=budgets[c]||0,over=lim&&sp>lim,pct=lim?Math.min(100,sp/lim*100):0;
    return `<div class="bud"><span>${c}</span><div><div class="track"><div class="fill ${over?"":"ok"}" style="width:${pct}%"></div></div><small style="color:var(--muted)">₹${fmt(sp)}${lim?" of ₹"+fmt(lim)+(over?" — over by ₹"+fmt(sp-lim):""):" spent, no limit set"}</small></div><input type="number" min="0" data-cat="${c}" value="${lim||""}" placeholder="Limit ₹" aria-label="${c} budget"></div>`}).join("");
}
function resetForm(){editId=null;$("sub").textContent="Add transaction";$("cancel").hidden=true;$("ftitle").textContent="Add a transaction"}
$("cancel").onclick=()=>{resetForm();$("amt").value="";$("note").value=""};
$("q").oninput=render;$("ftype").onchange=render;$("fcat").onchange=render;
document.addEventListener("change",e=>{const c=e.target.dataset&&e.target.dataset.cat;if(c){const v=parseFloat(e.target.value);if(v>0)budgets[c]=v;else delete budgets[c];save();render()}});
$("csv").onclick=async()=>{
  const rows=["date,type,category,amount,note",...tx.map(x=>[x.date,x.type,x.cat,x.amt,'"'+x.note.replace(/"/g,'""')+'"'].join(","))];
  try{await navigator.clipboard.writeText(rows.join("\n"));$("csv").textContent="Copied to clipboard"}catch(e){$("csv").textContent="Copy blocked by browser"}
  setTimeout(()=>$("csv").textContent="Copy as CSV",1800)};
document.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{type=b.dataset.t;document.querySelectorAll(".seg button").forEach(x=>x.setAttribute("aria-pressed",x===b));setCats()});
$("f").onsubmit=ev=>{ev.preventDefault();
  const amt=parseFloat($("amt").value);if(!(amt>0))return;
  const rec={type,amt,cat:$("cat").value,date:$("date").value,note:$("note").value.trim()};
  if(editId){tx=tx.map(t=>t.id===editId?{...t,...rec}:t);resetForm()}else tx.push({id:Date.now(),...rec});
  save();$("amt").value="";$("note").value="";render()};
$("month").onchange=e=>{month=e.target.value;render()};
document.addEventListener("click",e=>{
  if(e.target.classList.contains("del")){tx=tx.filter(x=>x.id!=e.target.dataset.id);save();render()}
  if(e.target.classList.contains("edit")){const x=tx.find(t=>t.id==e.target.dataset.id);if(!x)return;
    editId=x.id;type=x.type;document.querySelectorAll(".seg button").forEach(b=>b.setAttribute("aria-pressed",b.dataset.t===x.type));setCats(x.cat);
    $("amt").value=x.amt;$("date").value=x.date;$("note").value=x.note;$("sub").textContent="Save changes";$("cancel").hidden=false;$("ftitle").textContent="Edit transaction";$("f").scrollIntoView({behavior:"smooth"})}
  if(e.target.id==="demo"){const d=new Date(),p=n=>String(n).padStart(2,"0");
    const s=(mo,day,t,amt,cat,note)=>{const dt=new Date(d.getFullYear(),d.getMonth()-mo,day);return{id:Math.random()*1e13|0,type:t,amt,cat,note,date:`${dt.getFullYear()}-${p(dt.getMonth()+1)}-${p(dt.getDate())}`}};
    tx=[s(0,1,"income",45000,"Salary",""),s(0,3,"expense",12000,"Rent","October rent"),s(0,5,"expense",2400,"Food","Groceries"),s(0,9,"expense",800,"Transport","Fuel"),s(0,12,"expense",1500,"Bills","Electricity"),s(1,1,"income",45000,"Salary",""),s(1,2,"income",6000,"Freelance","Logo project"),s(1,3,"expense",12000,"Rent",""),s(1,10,"expense",3200,"Shopping","Clothes"),s(1,18,"expense",2100,"Food",""),s(2,1,"income",45000,"Salary",""),s(2,4,"expense",12000,"Rent",""),s(2,15,"expense",1800,"Fun","Movies")];
    save();render()}});
$("t1").onclick=$("t2").onclick=e=>{const one=e.target.id==="t1";$("t1").setAttribute("aria-selected",one);$("t2").setAttribute("aria-selected",!one);$("p1").hidden=!one;$("p2").hidden=one};
$("date").valueAsDate=new Date();
setCats();render();
