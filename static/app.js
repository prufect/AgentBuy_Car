/* ─── State ─────────────────────────────────────────────────────────────── */
let pollingTimer = null;
let currentJobId  = null;

/* ─── DOM refs ──────────────────────────────────────────────────────────── */
const $  = id => document.getElementById(id);
const formSection    = $('form-section');
const loadingSection = $('loading-section');
const resultsSection = $('results-section');
const errorSection   = $('error-section');

const form         = $('search-form');
const submitBtn    = $('submit-btn');
const progressList = $('progress-list');
const loadingTitle = $('loading-title');
const carCards     = $('car-cards');
const carTypeGrid  = $('car-type-grid');
const carTypeInput = $('car-type');

/* ─── Section helpers ───────────────────────────────────────────────────── */
function showOnly(active) {
  [formSection, loadingSection, resultsSection, errorSection].forEach(s => {
    s.classList.toggle('hidden', s !== active);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ─── Car Type Visual Selector ─────────────────────────────────────────── */
carTypeGrid.addEventListener('click', e => {
  const btn = e.target.closest('.car-type-btn');
  if (!btn) return;

  // Deselect all, select clicked
  carTypeGrid.querySelectorAll('.car-type-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  carTypeInput.value = btn.dataset.value;
});

/* ─── Form submit ───────────────────────────────────────────────────────── */
form.addEventListener('submit', async e => {
  e.preventDefault();

  const carType    = carTypeInput.value;
  const condition  = $('condition').value || null;
  const budgetMin  = parseInt($('budget-min').value);
  const budgetMax  = parseInt($('budget-max').value);
  const yearMin    = $('year-min').value ? parseInt($('year-min').value) : null;
  const yearMax    = $('year-max').value ? parseInt($('year-max').value) : null;
  const mileageMax = $('mileage-max').value ? parseInt($('mileage-max').value) : null;

  const mustHaveFeatures = [...document.querySelectorAll('.feature-chip input:checked')]
    .map(cb => cb.value);

  if (!carType) {
    carTypeGrid.style.outline = '2px solid var(--red)';
    setTimeout(() => carTypeGrid.style.outline = '', 2000);
    return;
  }
  if (isNaN(budgetMin) || isNaN(budgetMax)) return;

  submitBtn.disabled = true;
  submitBtn.querySelector('.btn-text').textContent = 'Searching...';

  try {
    const res = await fetch('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        car_type: carType,
        budget_min: budgetMin,
        budget_max: budgetMax,
        year_min: yearMin,
        year_max: yearMax,
        mileage_max: mileageMax,
        must_have_features: mustHaveFeatures,
        condition: condition,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const { job_id } = await res.json();
    currentJobId = job_id;

    renderProgressList([
      { step: 'scraping_carmax', status: 'pending' },
      { step: 'scraping_carvana', status: 'pending' },
      { step: 'scoring', status: 'pending' },
      { step: 'generating_summaries', status: 'pending' },
    ]);
    showOnly(loadingSection);
    startPolling(job_id);

  } catch (err) {
    showError(err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.querySelector('.btn-text').textContent = 'Search Cars';
  }
});

/* ─── Polling ───────────────────────────────────────────────────────────── */
function startPolling(jobId) {
  if (pollingTimer) clearInterval(pollingTimer);
  pollingTimer = setInterval(() => pollJob(jobId), 2000);
  pollJob(jobId);
}

async function pollJob(jobId) {
  try {
    const res = await fetch(`/search/${jobId}`);
    if (!res.ok) throw new Error(`Poll failed: HTTP ${res.status}`);
    const data = await res.json();

    if (loadingTitle) loadingTitle.textContent = data.progress || 'Searching...';
    if (data.progress_detail && Object.keys(data.progress_detail).length > 0) {
      renderProgressList(Object.values(data.progress_detail));
    }

    if (data.status === 'completed') {
      clearInterval(pollingTimer);
      renderResults(data.result);
    } else if (data.status === 'failed') {
      clearInterval(pollingTimer);
      showError(data.error || 'Search failed with an unknown error.');
    }
  } catch (err) {
    clearInterval(pollingTimer);
    showError('Network error: ' + err.message);
  }
}

/* ─── Progress list ─────────────────────────────────────────────────────── */
const STEP_LABELS = {
  scraping_carmax: 'Scanning CarMax',
  scraping_carvana: 'Scanning Carvana',
  scoring: 'Scoring & Ranking',
  generating_summaries: 'AI Summaries',
};

function renderProgressList(items) {
  progressList.innerHTML = items.map(item => {
    const statusLabel = {
      pending: 'Waiting',
      running: 'Working',
      done: 'Done',
      failed: 'Failed',
    }[item.status] || item.status;

    const stepLabel = STEP_LABELS[item.step] || item.step;

    return `
      <div class="progress-item ${item.status}">
        <div class="progress-dot"></div>
        <span class="progress-name">${esc(stepLabel)}</span>
        <span class="progress-status">${statusLabel}</span>
      </div>
    `;
  }).join('');
}

/* ─── Render results ────────────────────────────────────────────────────── */
function renderResults(result) {
  if (!result) { showError('No results returned.'); return; }

  const params = result.search_params;
  $('result-meta').textContent =
    `${result.total_found} cars found · ${formatDate(result.generated_at)}`;

  const paramsSummary = $('search-params-summary');
  const tags = [
    params.car_type,
    `$${params.budget_min.toLocaleString()} - $${params.budget_max.toLocaleString()}`,
    params.year_min ? `${params.year_min}+` : null,
    params.mileage_max ? `Under ${params.mileage_max.toLocaleString()} mi` : null,
    params.condition || null,
  ].filter(Boolean);

  paramsSummary.innerHTML = tags.map(t => `<span class="param-tag">${esc(t)}</span>`).join('');
  paramsSummary.classList.remove('hidden');

  carCards.innerHTML = result.cars.map((car, i) => renderCarCard(car, i)).join('');
  showOnly(resultsSection);
}

function renderCarCard(scoredCar, index) {
  const car = scoredCar.listing;
  const scores = scoredCar.scores;
  const composite = scores.composite;

  // Score color
  let scoreColor = 'var(--red)';
  if (composite >= 80) scoreColor = 'var(--green)';
  else if (composite >= 60) scoreColor = 'var(--yellow)';

  // Source class
  const sourceClass = car.source.toLowerCase() === 'carmax' ? 'source-carmax' : 'source-carvana';

  // Rank badge (top 3)
  let rankHtml = '';
  if (index < 3) {
    rankHtml = `<div class="rank-badge rank-${index + 1}">${index + 1}</div>`;
  }

  // Score ring SVG
  const circumference = 2 * Math.PI * 22; // radius = 22
  const offset = circumference - (composite / 100) * circumference;
  const ringHtml = `
    <div class="score-ring">
      <svg viewBox="0 0 56 56">
        <circle class="score-ring-bg" cx="28" cy="28" r="22" />
        <circle class="score-ring-fill" cx="28" cy="28" r="22"
          stroke="${scoreColor}"
          stroke-dasharray="${circumference}"
          stroke-dashoffset="${offset}" />
      </svg>
      <div class="score-ring-text" style="color:${scoreColor}">${Math.round(composite)}</div>
    </div>
  `;

  // Mini breakdown chips
  const breakdownItems = [
    { label: 'Price', value: scores.price_value },
    { label: 'Year', value: scores.year_depreciation },
    { label: 'Miles', value: scores.mileage },
    { label: 'Cond', value: scores.condition },
    { label: 'Feat', value: scores.feature_match },
  ];

  const breakdownHtml = breakdownItems.map(item => {
    let barColor = 'var(--accent)';
    if (item.value >= 80) barColor = 'var(--green)';
    else if (item.value >= 60) barColor = 'var(--yellow)';
    else barColor = 'var(--red)';

    return `
      <div class="breakdown-chip">
        <div class="breakdown-chip-bar">
          <div class="breakdown-chip-fill" style="width:${item.value}%;background:${barColor}"></div>
        </div>
        <span class="breakdown-chip-label">${esc(item.label)}</span>
        <span class="breakdown-chip-value" style="color:${barColor}">${item.value}</span>
      </div>
    `;
  }).join('');

  // Feature tags
  const featureHtml = (car.features || []).slice(0, 8).map(f =>
    `<span class="feature-tag">${esc(f)}</span>`
  ).join('');

  return `
    <article class="car-card">
      <div class="car-card-top">
        <div class="car-img-wrap">
          ${car.image_url ? `<img src="${esc(car.image_url)}" alt="${esc(car.title)}" onerror="this.parentElement.innerHTML='<div style=\\'display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:0.8rem\\'>No Image</div>'" />` : '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:0.8rem">No Image</div>'}
          ${rankHtml}
        </div>
        <div class="car-info">
          <div class="car-title-row">
            <h3 class="car-title">${esc(car.title)}</h3>
            <div class="car-price">$${car.price.toLocaleString()}</div>
          </div>
          <div class="car-meta">
            <span class="source-pill ${sourceClass}">${esc(car.source)}</span>
            ${car.year ? `<span class="meta-chip">${car.year}</span>` : ''}
            ${car.mileage != null ? `<span class="meta-chip">${car.mileage.toLocaleString()} mi</span>` : ''}
            ${car.condition ? `<span class="meta-chip">${esc(car.condition)}</span>` : ''}
          </div>
        </div>
      </div>

      <div class="score-ring-wrap">
        ${ringHtml}
        <div>
          <div class="score-ring-label">Match Score</div>
        </div>
        <div class="score-breakdown-mini">
          ${breakdownHtml}
        </div>
      </div>

      <div class="car-body">
        ${scoredCar.summary ? `
        <div class="car-section">
          <p class="ai-summary">${esc(scoredCar.summary)}</p>
        </div>` : ''}

        ${featureHtml ? `
        <div class="car-section">
          <div class="feature-tags">${featureHtml}</div>
        </div>` : ''}

        <div class="car-actions">
          <a href="${esc(car.url)}" target="_blank" rel="noopener" class="btn-view">
            View on ${esc(car.source)}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7M17 7H7M17 7v10"/></svg>
          </a>
        </div>
      </div>
    </article>
  `;
}

/* ─── Error ─────────────────────────────────────────────────────────────── */
function showError(msg) {
  $('error-text').textContent = msg;
  showOnly(errorSection);
}

/* ─── Reset ─────────────────────────────────────────────────────────────── */
function resetApp() {
  if (pollingTimer) clearInterval(pollingTimer);
  currentJobId = null;
  form.reset();
  carTypeInput.value = '';
  carTypeGrid.querySelectorAll('.car-type-btn').forEach(b => b.classList.remove('active'));
  showOnly(formSection);
}

$('new-search-btn').addEventListener('click', resetApp);

/* ─── Utils ─────────────────────────────────────────────────────────────── */
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch { return iso; }
}
