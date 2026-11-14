'use strict';

(() => {
  const byId = id => document.getElementById(id);
  const loader = byId('data-load');
  const input = byId('data-file');
  const status = byId('data-status');
  const oneDigit = new Intl.NumberFormat('en-GB', {maximumFractionDigits: 1});
  const fourDigits = new Intl.NumberFormat('en-GB', {maximumFractionDigits: 4});
  const datefmt = new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Berlin'
  });
  const number = Number.isFinite;

  function meter(node, value) {
    const bar = node.firstElementChild;
    if (!number(value)) {
      node.setAttribute('aria-hidden', 'true');
      return;
    }
    const percent = Math.max(0, Math.min(100, value));
    node.setAttribute('role', 'meter');
    node.setAttribute('aria-valuemin', '0');
    node.setAttribute('aria-valuemax', '100');
    node.setAttribute('aria-valuenow', String(percent));
    node.removeAttribute('aria-hidden');
    bar.classList.toggle('low', percent < 50);
    bar.classList.toggle('mid', percent >= 50 && percent < 70);
    bar.style.width = percent + '%';
  }

  function show(data) {
    if (!data || typeof data.version !== 'string' ||
        (data.latest != null && (!data.latest.health || !data.latest.measurements))) {
      throw new Error('Choose the plant_health.json file produced by the analysis.');
    }
    const row = data.latest;
    if (!row) {
      status.textContent = 'Run the image analysis first.';
      return;
    }
    const {health, measurements} = row;
    const score = health.health_score;
    const reason = key => row.missing?.[key] || 'Unavailable for this photo';

    if (row.captured_at && Number.isFinite(Date.parse(row.captured_at))) {
      const time = byId('capture-time');
      time.dateTime = row.captured_at;
      time.textContent = datefmt.format(new Date(row.captured_at));
      time.hidden = false;
      byId('capture-unknown').hidden = true;
    }
    byId('timestamp').hidden = false;

    if (typeof row.photo === 'string' && /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(row.photo)) {
      const photo = byId('plant-photo');
      const fallback = byId('no-photo');
      photo.addEventListener('load', () => {
        photo.hidden = false;
        fallback.hidden = true;
      }, {once: true});
      photo.src = row.photo;
    }
    const category = byId('health-category');
    category.textContent = row.category_label || 'No score';
    category.classList.toggle('check', !number(score) || score < 70);
    if (number(score)) {
      byId('score').classList.remove('absent');
      byId('score-value').textContent = oneDigit.format(score);
      byId('score-unit').hidden = false;
      const scoreMeter = byId('score-meter');
      meter(scoreMeter, score);
      scoreMeter.hidden = false;
    } else {
      byId('score').setAttribute('aria-label', 'No score');
      const note = byId('score-status');
      note.title = reason('health_score');
      note.textContent = row.status_label || 'No score';
      note.hidden = false;
    }
    for (const part of document.querySelectorAll('[data-part]')) {
      const key = part.dataset.part;
      const value = health[key];
      const label = part.querySelector('strong');
      if (number(value)) {
        label.textContent = oneDigit.format(value) + ' / 100';
      } else {
        label.title = reason(key);
        label.setAttribute('aria-label', 'Unavailable');
      }
      meter(part.querySelector('[data-meter]'), value);
    }
    for (const entry of document.querySelectorAll('[data-field]')) {
      const value = measurements[entry.dataset.field];
      if (number(value)) {
        const format = entry.dataset.digits === '4' ? fourDigits : oneDigit;
        entry.textContent = format.format(value) + (entry.dataset.unit || '');
      }
    }
    const color = measurements.color_hex;
    if (typeof color === 'string' && /^#[0-9a-f]{6}$/i.test(color)) {
      const swatch = byId('color-swatch');
      swatch.style.backgroundColor = color;
      swatch.hidden = false;
      byId('color-hex').textContent = color.toUpperCase();
    }
    byId('empty').hidden = true;
    byId('dashboard').hidden = false;
  }

  function askForFile(message) {
    status.textContent = message;
    loader.hidden = false;
  }

  input.addEventListener('change', async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      show(JSON.parse(await file.text()));
    } catch (error) {
      askForFile(error instanceof SyntaxError ? 'The JSON file could not be read.' : error.message);
      input.value = '';
    }
  });
  if (location.protocol === 'file:') {
    askForFile('Run python -B health_assessment.py to load the data automatically, or choose plant_health.json.');
    return;
  }
  (async () => {
    try {
      const response = await fetch('plant_health.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('No plant health data found. Run the image analysis first.');
      show(await response.json());
    } catch (error) {
      askForFile(error instanceof SyntaxError ? 'The JSON file could not be read.' : error.message);
    }
  })();
})();
