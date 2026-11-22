import {field, form} from '../components/common/forms.js';
import {empty, heading, status, table} from '../components/common/layout.js';
import {phase} from '../constants/labels.js';
import {state} from '../stores/studio.js';
import {dateTime, esc, signed} from '../utils/format.js';

const basisText = run => run.arrangement === 'withdrawn' ? '已撤下 · 历史依据'
  : run.basis_revision === run.revision ? '生效中 · 当前依据' : '生效中 · 历史依据';
const basisBadge = run => status(basisText(run), run.arrangement === 'active' && run.basis_revision === run.revision ? 'signal' : 'alert');

const directionsOf = item => {
  if (!item.directions) return '—';
  if (item.directions.consistent === true) return status('方向一致', 'signal');
  if (item.directions.consistent === false) return status('方向不一致', 'alert');
  return status('无参照方向');
};

const runsTable = run => (run.runs ?? []).length ? table(['版本', '触发', '状态', '方向核对', '入账', '完成时间', '操作'],
  run.runs.map(item => `<tr><td class="mono">r${item.revision}${item.revision === run.basis_revision ? '<small>安排依据</small>' : ''}</td>
    <td>${item.correction_id ? `补正 #${item.correction_id}` : '初次计算'}</td><td>${phase[item.state]}</td>
    <td>${directionsOf(item)}</td><td>${item.applied ? '已入账' : '已被更新补正取代'}</td><td>${dateTime(item.finished_at)}</td>
    <td><div class="chips"><button class="text-button" data-run-export="${item.revision}">导出</button><button class="text-button" data-recheck="${item.revision}">复算</button></div></td></tr>`)) : '';

export function retest() {
  const run = state.detail;
  const arrangements = state.diagnostics.filter(item => item.reviewed_at);
  const candidates = state.diagnostics.filter(item => item.state === 'complete' && !item.reviewed_at);
  let detail;
  if (run?.reviewed_at) {
    const withdrawn = run.arrangement === 'withdrawn';
    detail = `<div class="retest-detail"><h2>${esc(run.title)}</h2><p>${basisBadge(run)}</p>
      <dl class="metadata"><div><dt>变量版本</dt><dd>${esc(run.version)}</dd></div><div><dt>数据版本</dt><dd>r${run.revision}</dd></div><div><dt>安排依据</dt><dd>r${run.basis_revision}</dd></div><div><dt>配对样本</dt><dd>${run.result?.n ?? '—'} 条</dd></div><div><dt>原始 r</dt><dd>${signed(run.result?.raw)}</dd></div><div><dt>控制后 r</dt><dd>${signed(run.result?.partial)}</dd></div></dl>
      ${withdrawn ? `<p class="notice" role="alert">${esc(run.withdraw_note || '安排已撤下，等待业务负责人复核。')}<br><small>${dateTime(run.withdrawn_at)}</small></p>` : ''}
      <div class="decision"><h3>隔音复测安排</h3><p>${esc(run.decision)}</p><small>${esc(run.reviewer)} · ${dateTime(run.reviewed_at)}</small></div>
      ${withdrawn && state.account.role === 'admin' ? (run.state === 'complete' ? form('publish', field('复核结论', '<textarea name="text" rows="4" minlength="8" maxlength="500" placeholder="核对最新计算与补正台账后，记录复核结论并重新发布。" required></textarea>'), '复核后重新发布') : '<p class="notice">等待最新重算完成后才能复核发布。</p>') : ''}
      <h3>计算记录</h3>${runsTable(run)}
      <div class="panel-actions"><button class="secondary" data-download>导出当前清单</button></div>
      <a class="text-link" href="#diagnostics/${run.id}">返回计算证据 →</a></div>`;
  } else if (run?.state === 'complete') {
    detail = `<div class="retest-detail"><h2>${esc(run.title)}</h2><p>${status('待复核', 'signal')}</p>
      <dl class="metadata"><div><dt>变量版本</dt><dd>${esc(run.version)}</dd></div><div><dt>配对样本</dt><dd>${run.result.n} 条</dd></div><div><dt>原始 r</dt><dd>${signed(run.result.raw)}</dd></div><div><dt>控制后 r</dt><dd>${signed(run.result.partial)}</dd></div></dl>
      ${state.account.role === 'admin' ? form('publish', field('隔音复测安排', '<textarea name="text" rows="4" minlength="8" maxlength="500" placeholder="记录复测时间、固定的风机档位和测点，以及需复验的现场条件。" required></textarea>'), '发布复测清单') : '<p class="notice">等待业务负责人记录复测安排并发布。</p>'}
      <a class="text-link" href="#diagnostics/${run.id}">返回计算证据 →</a></div>`;
  } else {
    detail = empty('请选择一张诊断单', '计算完成并由业务负责人复核后，复测安排会显示在这里。');
  }
  const link = item => `<a href="#retest/${item.id}" ${item.id === run?.id ? 'aria-current="page"' : ''}><strong>${esc(item.title)}</strong><small>${item.reviewed_at ? basisText(item) : `待复核 · ${esc(item.version)}`}</small></a>`;
  return `${heading('隔音复测清单', '复核关联变化，安排固定时段、风机与测点的复测。')}
    <div class="split"><section class="bound"><div class="section-label"><h2>复测安排</h2></div>${detail}</section>
    <aside class="inset"><h2>复测安排</h2>${arrangements.length ? `<div class="run-list">${arrangements.map(link).join('')}</div>` : '<p>当前没有已发布的复测安排。</p>'}
    <h2>待复核诊断</h2>${candidates.length ? `<div class="run-list">${candidates.map(link).join('')}</div>` : '<p>没有等待复核的诊断。</p>'}</aside></div>`;
}
