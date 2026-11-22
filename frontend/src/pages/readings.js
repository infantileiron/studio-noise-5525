import {field, form, select} from '../components/common/forms.js';
import {empty, heading, table, status} from '../components/common/layout.js';
import {band, hvac, position} from '../constants/labels.js';
import {state, writable} from '../stores/studio.js';
import {dateTime, esc, level} from '../utils/format.js';

const changes = item => [
  item.noise_before != null ? `LAeq ${level(item.noise_before)} → ${level(item.noise_after)}` : '',
  item.traffic_before != null ? `车流 ${item.traffic_before} → ${item.traffic_after}` : '',
].filter(Boolean).join('，');

export function readings() {
  const sessions = Object.fromEntries(state.sessions.map(s => [s.id, `${s.code} · ${s.title}`]));
  const visible = state.filter ? state.readings.filter(row => String(row.session_id) === state.filter) : state.readings;
  const rows = visible.map(row => `<tr><td title="${esc(row.note)}"><strong class="mono">${esc(row.reference)}</strong><small>${esc(row.code)} · ${band[row.band]}</small>${row.correction_count ? status(`补正×${row.correction_count}`, 'alert') : ''}</td><td>${status(hvac[row.hvac])}</td><td>${position[row.position]}</td><td class="numeric">${row.traffic}</td><td class="numeric reading-level">${level(row.noise)}</td></tr>`);
  const targets = Object.fromEntries(visible.map(row => [row.id, `${row.reference}（${row.code}）`]));
  const correctionForm = writable() && visible.length ? `<h2>补正声测</h2>${form('corrections',
    field('补正声测', select('reading_id', targets, '', '选择要补正的声测')) +
    '<p class="muted" data-current hidden></p>' +
    `<div class="pair">${field('补正 LAeq／dB(A)', '<input type="number" name="noise" min="0" max="140" step="0.01" placeholder="留空则不补正">')}${field('补正车流／辆', '<input type="number" name="traffic" min="0" max="1000" placeholder="留空则不补正">')}</div>` +
    field('补正理由', '<textarea name="reason" rows="2" minlength="4" maxlength="350" placeholder="声级仪校准结论与偏差依据" required></textarea>'), '补正入账')}` : '';
  const ledger = `<h2>补正台账</h2><div class="ledger">${state.corrections.map(item => `<p><strong class="mono">${esc(item.reference)}</strong> ${esc(changes(item))}<small>${esc(item.reason)} · ${esc(item.actor)} · ${dateTime(item.created_at)}</small></p>`).join('') || '<p>暂无补正记录。</p>'}</div>`;
  return `${heading('声测记录', '同一无声段的 60 秒 LAeq 与车流记录。', '<a class="secondary" href="#methods">查看变量版本 →</a>')}
    <div class="split"><section class="bound"><div class="section-label"><h2>配对声测 <small>${visible.length} 条</small></h2>
    <label class="select-inline"><span>时段</span>${select('filter', sessions, state.filter, '全部时段')}</label></div>
    ${rows.length ? table(['声测编号', '风机', '测点', '车流／辆', 'LAeq／dB(A)'], rows, 'readings-table') : empty('该范围没有声测', '先登记录音时段，再同步记录声级和车流。')}</section>
    <aside class="inset"><h2>${writable() ? '录入声测' : '录入规则'}</h2>${writable() && state.sessions.length ? form('readings',
      field('录音时段', select('session_id', sessions, state.filter)) +
      field('声测编号', '<input name="reference" maxlength="64" placeholder="FS-1121-A-001" required>') +
      `<div class="pair">${field('风机档位', select('hvac', hvac))}${field('测点', select('position', position))}</div>` +
      `<div class="pair">${field('车流／辆', '<input type="number" name="traffic" min="0" max="1000" required>')}${field('LAeq／dB(A)', '<input type="number" name="noise" min="0" max="140" step="0.01" required>')}</div>` +
      field('备注', '<textarea name="note" rows="2" maxlength="350" placeholder="测量文件名或现场情况"></textarea>'), '保存声测') : '<p>选择已有时段，即可查看该时段的有效配对记录。</p>'}
    ${correctionForm}${ledger}</aside></div>`;
}
