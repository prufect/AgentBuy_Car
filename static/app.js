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

/* ─── Section helpers ───────────────────────────────────────────────────── */
function showOnly(active) {
  [formSection, loadingSection, resultsSection, errorSection].forEach(s => {
    s.classList.toggle('hidden', s !== active);
  });
}

/* ─── Form submit ───────────────────────────────────────────────────────── */
form.addEventListener('submit', async e => {
  e.preventDefault();

  const carType    = $('car-type').value;
  const condition  = $('condition').value || null;
  const budgetMin  = parseInt($('budget-min').value);
  const budgetMax  = parseInt($('budget-max').value);
  const yearMin    = $('year-min').value ? parseInt($('year-min').value) : null;
  const yearMax    = $('year-max').value ? parseInt($('year-max').value) : null;
  const mileageMax = $('mileage-max').value ? parseInt($('mileage-max').value) : null;

  // Collect checked features
  const mustHaveFeatures = [...document.querySelectorAll('.feature-checkbox input:checked')]
    .map(cb => cb.value);

  if (!carType || isNaN(budgetMin) || isNaN(budgetMax)) return;

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

    // Show progress immediately
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
    submitBtn.querySelector('.btn-text').textContent = 'Find My Car';
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
  generating_summaries: 'Generating AI Summaries',
};

function renderProgressList(items) {
  progressList.innerHTML = items.map(item => {
    const statusLabel = {
      pending:     'Waiting...',
      running:     'In Progress...',
      done:        'Done',
      failed:      'Failed',
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
    `${result.total_found} cars found · Generated ${formatDate(result.generated_at)}`;

  // Search params summary
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

  carCards.innerHTML = result.cars.map(renderCarCard).join('');
  showOnly(resultsSection);
}

function renderCarCard(scoredCar, index) {
  const car = scoredCar.listing;
  const scores = scoredCar.scores;
  const composite = scores.composite;

  // Score color
  let scoreClass = 'score-low';
  if (composite >= 80) scoreClass = 'score-high';
  else if (composite >= 60) scoreClass = 'score-mid';

  // Source tag
  const sourceClass = car.source.toLowerCase() === 'carmax' ? 'source-carmax' : 'source-carvana';

  // Score breakdown bars
  const breakdownItems = [
    { label: 'Price Value', value: scores.price_value },
    { label: 'Year', value: scores.year_depreciation },
    { label: 'Mileage', value: scores.mileage },
    { label: 'Condition', value: scores.condition },
    { label: 'Features', value: scores.feature_match },
    { label: 'Source Trust', value: scores.source_trust },
  ];

  const breakdownHtml = breakdownItems.map(item => `
    <div class="breakdown-row">
      <span class="breakdown-label">${esc(item.label)}</span>
      <div class="breakdown-bar-bg">
        <div class="breakdown-bar" style="width: ${item.value}%"></div>
      </div>
      <span class="breakdown-value">${item.value}</span>
    </div>
  `).join('');

  // Feature tags
  const featureHtml = (car.features || []).slice(0, 6).map(f =>
    `<span class="feature-tag">${esc(f)}</span>`
  ).join('');

  return `
    <article class="car-card">
      <div class="car-header">
        <div class="car-header-left">
          ${car.image_url ? `<img class="car-image" src="${esc(car.image_url)}" alt="${esc(car.title)}" onerror="this.style.display='none'" />` : ''}
          <div class="car-title-block">
            <h3 class="car-title">${esc(car.title)}</h3>
            <div class="car-tags">
              <span class="source-tag ${sourceClass}">${esc(car.source)}</span>
              ${car.year ? `<span class="info-tag">${car.year}</span>` : ''}
              ${car.mileage != null ? `<span class="info-tag">${car.mileage.toLocaleString()} mi</span>` : ''}
              ${car.condition ? `<span class="info-tag">${esc(car.condition)}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="car-header-right">
          <div class="car-price">$${car.price.toLocaleString()}</div>
          <div class="score-badge ${scoreClass}">
            <span class="score-value">${composite}</span>
            <span class="score-label">/ 100</span>
          </div>
        </div>
      </div>

      <div class="car-body">
        ${scoredCar.summary ? `
        <div class="car-section">
          <p class="section-label">AI Summary</p>
          <p class="ai-summary">${esc(scoredCar.summary)}</p>
        </div>` : ''}

        <div class="car-section">
          <p class="section-label">Score Breakdown</p>
          <div class="breakdown">
            ${breakdownHtml}
          </div>
        </div>

        ${featureHtml ? `
        <div class="car-section">
          <p class="section-label">Features</p>
          <div class="feature-tags">${featureHtml}</div>
        </div>` : ''}

        <a href="${esc(car.url)}" target="_blank" rel="noopener" class="btn btn-outline">
          View on ${esc(car.source)} →
        </a>
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
