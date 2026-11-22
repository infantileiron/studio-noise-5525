export const payload = {
  sessions: form => Object.fromEntries(form),
  readings: form => ({...Object.fromEntries(form),
    session_id: Number(form.get('session_id')), traffic: Number(form.get('traffic')), noise: Number(form.get('noise')),
  }),
  corrections: form => {
    const body = {reading_id: Number(form.get('reading_id')), reason: form.get('reason')};
    if (!body.reading_id) throw new Error('请选择要补正的声测');
    if (form.get('noise') !== '') body.noise = Number(form.get('noise'));
    if (form.get('traffic') !== '') body.traffic = Number(form.get('traffic'));
    if (body.noise === undefined && body.traffic === undefined) throw new Error('至少填写 LAeq 或车流中一项补正值');
    return body;
  },
  methods: form => ({...Object.fromEntries(form), controls: form.getAll('controls')}),
  diagnostics: form => ({title: form.get('title'), method_id: Number(form.get('method_id')),
    session_ids: form.getAll('session_ids').map(Number),
  }),
};
