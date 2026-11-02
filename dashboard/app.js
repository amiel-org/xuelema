let data;
let currentView = 'overview';
let atlasSubject = '全部学科';
let atlasStatus = 'all';
let bankSubject = '全部学科';
let bankYear = '全部年份';
const selected = new Set();
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusNames = {good:'基本掌握',improve:'已有改善',have:'已有做对',wait:'还需补充',linked:'关系待复核',none:'暂无孩子证据'};
const taskNames = {completed:'已完成',awaiting_review:'待复核',running:'进行中',failed:'需介入'};

function head(title, description) {
  return `<div class="section-head"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div></div>`;
}
function renderOverview() {
  $('view-overview').innerHTML = head('六科当前重点', '先看下一步做什么；确认状态与候选关系分开呈现。') + `<div class="subject-grid">${data.subjects.map(s => {
    const targets = data.targets.filter(t => t.subject === s.name);
    const mastered = targets.filter(t => t.status === 'good').length;
    const pct = s.reviewed_targets ? Math.round(mastered / s.reviewed_targets * 100) : 0;
    return `<article class="subject-card" style="--subject:${esc(s.color)}"><div class="subject-head"><span class="subject-icon">${esc(s.icon)}</span><h2>${esc(s.name)}</h2><span class="mastery"><b>${pct}%</b>基本掌握</span></div><div class="meter" title="${mastered}/${s.reviewed_targets} 个已评估目标达到基本掌握"><span style="width:${pct}%"></span></div><h3>${esc(s.focus)}</h3><span class="next-label">下一步</span><p>${esc(s.next_action)}</p></article>`;
  }).join('')}</div><div class="notice">百分比的分母是“已评估目标”，不是完整教材目录；没有证据不等于不会。点击上方“目标图谱”查看具体证据。</div>`;
}
function renderAtlas() {
  const subjects = ['全部学科', ...data.subjects.map(s => s.name)];
  const rows = data.targets.filter(t => (atlasSubject === '全部学科' || t.subject === atlasSubject) && (atlasStatus === 'all' || t.status === atlasStatus));
  $('view-atlas').innerHTML = head('统一目标图谱', '目标关联是目录，原始证据才是学情依据。默认不强行映射未确认内容。') + `<div class="filters"><select id="atlasSubject" aria-label="按学科筛选">${subjects.map(s => `<option ${s===atlasSubject?'selected':''}>${esc(s)}</option>`).join('')}</select><select id="atlasStatus" aria-label="按证据状态筛选">${Object.entries({all:'全部状态',...statusNames}).map(([k,v]) => `<option value="${k}" ${k===atlasStatus?'selected':''}>${v}</option>`).join('')}</select></div><div class="target-grid">${rows.map(t => `<article class="target-card"><div class="target-top"><span class="tag">${esc(t.subject)} · ${esc(t.group)}</span><span class="status ${esc(t.status)}">${statusNames[t.status]}</span></div><h3>${esc(t.name)}</h3><p>${esc(t.summary)}</p><details><summary>${t.evidence.length} 条证据 · ${t.records.length} 条题录关联</summary>${t.evidence.map(e => `<div class="evidence"><b>${esc(e.type)}</b>：${esc(e.fact)}<small>${esc(e.date)} · ${esc(e.source)}</small></div>`).join('') || '<p>没有可确认证据；不从“未出现”推断“没学过”。</p>'}${t.records.map(id => `<small class="record-id">${esc(id)}</small>`).join('')}</details></article>`).join('') || '<div class="empty">本筛选没有目标。</div>'}</div>`;
  $('atlasSubject').addEventListener('change', e => {atlasSubject=e.target.value;renderAtlas()});
  $('atlasStatus').addEventListener('change', e => {atlasStatus=e.target.value;renderAtlas()});
}
function renderBank() {
  const years = ['全部年份', ...new Set(data.records.map(r => r.year))];
  const rows = data.records.filter(r => (bankSubject==='全部学科'||r.subject===bankSubject) && (bankYear==='全部年份'||r.year===Number(bankYear)));
  $('view-bank').innerHTML = head('目标关联题录', '按学科、目标与年份查找；勾选多条可统一排版。公开仓库只含虚构演示题。') + `<div class="filters"><select id="bankSubject" aria-label="按学科筛选">${['全部学科',...data.subjects.map(s=>s.name)].map(s=>`<option ${s===bankSubject?'selected':''}>${esc(s)}</option>`).join('')}</select><select id="bankYear" aria-label="按年份筛选">${years.map(y=>`<option ${String(y)===String(bankYear)?'selected':''}>${y}</option>`).join('')}</select></div><div class="record-list">${rows.map(r => `<label class="record"><input type="checkbox" data-record="${esc(r.id)}" ${selected.has(r.id)?'checked':''}><div class="record-body"><h3>${esc(r.subject)} · ${esc(r.year)} · ${esc(r.question_no)}｜${esc(r.title)}</h3><p>${r.target_ids.map(id=>esc(data.targets.find(t=>t.id===id)?.name||id)).join(' / ')}</p><div class="record-id">${esc(r.id)}</div></div></label>`).join('') || '<div class="empty">本筛选没有题录。</div>'}</div>`;
  $('bankSubject').addEventListener('change',e=>{bankSubject=e.target.value;renderBank()});
  $('bankYear').addEventListener('change',e=>{bankYear=e.target.value;renderBank()});
  document.querySelectorAll('[data-record]').forEach(el=>el.addEventListener('change',()=>{el.checked?selected.add(el.dataset.record):selected.delete(el.dataset.record);updateSelection()}));
}
function renderReviews() {
  $('view-reviews').innerHTML = head('周／月学习复盘', '发现什么 → 原始依据 → 下一步行动 → 等新作答验证。') + data.reviews.map(r=>`<article class="review-card"><div class="review-meta"><span class="tag">${esc(r.kind)}</span><small>交付 ${esc(r.completed_on)}</small></div><h3>${esc(r.period)}</h3><p>${esc(r.summary)}</p><details><summary>交付限制与来源</summary><div class="evidence">${esc(r.limitations)}<small>${esc(r.source)} · ${esc(r.id)}</small></div></details></article>`).join('');
}
function renderTasks() {
  $('view-tasks').innerHTML = head('执行任务', '状态变化应来自真实任务记录；待复核不等于完成。') + data.tasks.map(t=>`<article class="task-card"><div class="task-head"><span class="task-dot ${esc(t.status)}"></span><h3>${esc(t.title)}</h3><span class="status">${esc(taskNames[t.status]||t.status)}</span></div><p>${esc(t.note)}</p><small>${esc(t.owner)} · ${esc(t.updated_at)} · ${esc(t.id)}</small></article>`).join('');
}
function updateSelection() {
  $('selectedCount').textContent=selected.size;
  $('printSelection').hidden=currentView!=='bank';
}
function switchView(view) {
  currentView=view;
  document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==`view-${view}`);
  document.querySelectorAll('.nav-button').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  if(view==='atlas')renderAtlas();
  if(view==='bank')renderBank();
  if(view==='reviews')renderReviews();
  if(view==='tasks')renderTasks();
  updateSelection();
  history.replaceState(null,'',`#${view}`);
  window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('[data-view]').forEach(el=>el.addEventListener('click',()=>switchView(el.dataset.view)));
$('printSelection').addEventListener('click',()=>{
  $('printContent').innerHTML=data.records.filter(r=>selected.has(r.id)).map(r=>`<article class="print-item"><h3>${esc(r.subject)} · ${esc(r.year)} · ${esc(r.question_no)}｜${esc(r.title)}</h3><p>${esc(r.prompt)}</p><small>${esc(r.id)}</small></article>`).join('');
  $('printDialog').showModal();
});
$('printNow').addEventListener('click',()=>window.print());
async function start() {
  try {
    const response=await fetch('/api/dashboard');
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    data=await response.json();
    $('term').textContent=`${data.meta.term} · ${data.meta.student_label}`;
    $('reviewDate').textContent=data.meta.review_date;
    $('reviewPeriod').textContent=data.meta.review_period;
    $('notice').textContent=data.meta.notice;
    renderOverview();
    switchView(location.hash.slice(1) || 'overview');
  } catch(error) {
    $('notice').textContent=`看板读取失败：${error.message}`;
  }
}
start();
