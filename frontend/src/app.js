import {request} from './api/studio.js';
import {drawPlots} from './components/correlation.js';
import {shell} from './components/shell.js';
import {poll} from './hooks/poll.js';
import {calendar} from './pages/calendar.js';
import {diagnostics} from './pages/diagnostics.js';
import {login} from './pages/login.js';
import {methods} from './pages/methods.js';
import {readings} from './pages/readings.js';
import {retest} from './pages/retest.js';
import {location} from './router/pages.js';
import {refresh, signOut, state} from './stores/studio.js';
import {payload} from './types/forms.js';
import {save} from './utils/download.js';
import {esc} from './utils/format.js';

const app = document.querySelector('#app');
const renderers = {calendar, readings, methods, diagnostics, retest};
let notice = '';
let stopPoll = () => {};
let revision = 0;

function render(error = '') {
  if (!state.account) { app.innerHTML = login(); return; }
  const {key} = location();
  const body = error ? `<div class="notice" role="alert">${esc(error)} <button data-retry>重试</button></div>` : renderers[key]();
  app.innerHTML = shell(key, state.account, body, notice);
  drawPlots(state.detail);
}

async function show() {
  const current = ++revision;
  stopPoll();
  if (!state.account) { render(); return; }
  const {key, id} = location();
  try {
    const detail = id && ['diagnostics', 'retest'].includes(key) ? await request(`/diagnostics/${id}`) : null;
    if (revision !== current) return;
    state.detail = detail;
    render();
    if (detail?.state === 'queued') {
      stopPoll = poll(async () => {
        try {
          const updated = await request(`/diagnostics/${detail.id}`);
          if (revision !== current || updated.state === 'queued') return;
          await refresh();
          if (revision !== current) return;
          state.detail = updated;
          stopPoll();
          render();
        } catch (error) {
          if (revision !== current) return;
          stopPoll();
          render(error.message);
        }
      }, 650);
    }
  } catch (error) {
    if (revision === current) render(error.message);
  }
}

app.addEventListener('submit', async event => {
  const target = event.target.closest('form[data-resource]');
  if (!target) return;
  event.preventDefault();
  const resource = target.dataset.resource;
  const form = new FormData(target);
  const button = target.querySelector('[type=submit]');
  const errorBox = target.querySelector('.form-error');
  button.disabled = true;
  errorBox.hidden = true;
  try {
    if (resource === 'login') {
      const response = await request('/auth/login', {body: Object.fromEntries(form)});
      sessionStorage.setItem('studio.token', response.token);
      try { await refresh(); }
      catch (error) { signOut(); throw error; }
      state.account = response.account;
      notice = '';
      await show();
      return;
    }
    if (resource === 'publish') {
      await request(`/diagnostics/${state.detail.id}/publish`, {body: Object.fromEntries(form)});
      notice = '复测清单已发布，观察员现在可以查看。';
    } else {
      const body = payload[resource](form);
      if (resource === 'diagnostics' && !body.session_ids.length) throw new Error('至少选择一个时段');
      const record = await request('/' + resource, {body});
      notice = {sessions:'录音时段已保存。', readings:'声测已保存。', methods:'变量版本已保存。', diagnostics:'诊断已提交。', corrections:'补正已入账，受影响的诊断已排队重算。'}[resource];
      await refresh();
      if (resource === 'diagnostics') { window.location.hash = `diagnostics/${record.id}`; return; }
      await show();
      return;
    }
    await refresh();
    await show();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    if (error.status === 401 && state.account) {
      signOut();
      await show();
    }
  } finally { button.disabled = false; }
});

app.addEventListener('change', event => {
  if (event.target.matches('[name=filter]')) { state.filter = event.target.value; render(); }
  if (event.target.matches('[name=reading_id]')) {
    const hint = event.target.form.querySelector('[data-current]');
    const reading = state.readings.find(row => row.id === Number(event.target.value));
    hint.hidden = !reading;
    if (reading) hint.textContent = `当前 LAeq ${Number(reading.noise).toFixed(2)} dB(A)，车流 ${reading.traffic} 辆；补正后原值留存在台账。`;
  }
  if (event.target.matches('[name=predictor]')) {
    for (const option of event.target.form.querySelectorAll('[name=controls]')) {
      option.disabled = option.value === event.target.value;
      if (option.disabled) option.checked = false;
    }
  }
});
app.addEventListener('click', async event => {
  const element = event.target.closest('[data-demo],[data-filter],[data-logout],[data-download],[data-retry],[data-recheck],[data-run-export]');
  if (!element) return;
  if (element.dataset.demo) {
    const form = app.querySelector('form');
    form.elements.email.value = `${element.dataset.demo}@demo.local`;
    form.elements.password.value = 'Tape2026!';
    form.elements.email.focus();
  }
  if (element.dataset.filter) state.filter = element.dataset.filter;
  if (element.hasAttribute('data-logout')) { signOut(); notice = ''; window.location.hash = 'calendar'; await show(); }
  if (element.hasAttribute('data-retry')) await show();
  if (element.hasAttribute('data-download')) {
    try { await save(await request(`/diagnostics/${state.detail.id}/export`, {raw: true})); }
    catch (error) { notice = error.message; render(); }
  }
  if (element.dataset.runExport !== undefined) {
    try { await save(await request(`/diagnostics/${state.detail.id}/runs/${element.dataset.runExport}/export`, {raw: true})); }
    catch (error) { notice = error.message; render(); }
  }
  if (element.dataset.recheck !== undefined) {
    try {
      const result = await request(`/diagnostics/${state.detail.id}/runs/${element.dataset.recheck}/recheck`, {body: {}});
      notice = result.match ? `r${result.revision} 复算一致，旧结果可复现。` : `r${result.revision} 复算不一致，请核查计算环境。`;
      render();
    } catch (error) { notice = error.message; render(); }
  }
});
window.addEventListener('hashchange', () => { notice = ''; show(); window.scrollTo(0, 0); });
window.addEventListener('resize', () => drawPlots(state.detail));

if (sessionStorage.getItem('studio.token')) {
  try { state.account = await request('/auth/me'); await refresh(); }
  catch { signOut(); }
}
await show();
