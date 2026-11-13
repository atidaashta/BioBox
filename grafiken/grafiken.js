'use strict';

(() => {
  const tabs = [...document.querySelectorAll('nav a[data-file]')];
  const toolbar = document.getElementById('chart-toolbar');
  const open = document.getElementById('chart-open');
  const image = document.getElementById('chart-image');
  const status = document.getElementById('chart-status');
  let available = [];

  function probe(file) {
    const png = new Image();
    return new Promise(resolve => {
      png.onload = () => resolve(true);
      png.onerror = () => resolve(false);
      png.src = file;
    });
  }

  async function availableTabs() {
    if (location.protocol !== 'file:') {
      try {
        const response = await fetch('grafiken.json', {cache: 'no-store'});
        if (response.ok) {
          const data = await response.json();
          if (Array.isArray(data?.charts)) {
            const files = new Set(data.charts.map(chart => chart?.file));
            return tabs.filter(tab => files.has(tab.dataset.file));
          }
        }
      } catch {
        // The PNGs can also be read when a manifest is unavailable.
      }
    }
    const found = await Promise.all(tabs.map(tab => probe(tab.dataset.file)));
    return tabs.filter((_, index) => found[index]);
  }

  function showChart() {
    const tab = available.find(item => item.hash === location.hash) || available[0];
    if (!tab) return;
    const label = tab.textContent.trim();
    const file = tab.dataset.file;
    for (const item of available) {
      if (item === tab) item.setAttribute('aria-current', 'true');
      else item.removeAttribute('aria-current');
    }
    open.hidden = true;
    image.hidden = true;
    status.hidden = false;
    status.textContent = 'Grafik wird geladen …';
    image.alt = label;
    open.href = file;
    open.setAttribute('aria-label', label + ' als PNG öffnen');
    image.onload = () => {
      status.hidden = true;
      image.hidden = false;
      open.hidden = false;
    };
    image.onerror = () => {
      status.textContent = 'Grafik nicht verfügbar.';
    };
    if (image.getAttribute('src') !== file) image.src = file;
    else if (image.complete) {
      if (image.naturalWidth) image.onload();
      else image.onerror();
    }
  }

  (async () => {
    available = await availableTabs();
    if (!available.length) {
      status.textContent = 'Keine Grafiken verfügbar.';
      return;
    }
    for (const tab of tabs) tab.hidden = !available.includes(tab);
    toolbar.hidden = false;
    window.addEventListener('hashchange', showChart);
    showChart();
  })();
})();
