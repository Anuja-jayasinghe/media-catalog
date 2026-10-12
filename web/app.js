const form = document.querySelector('#search-form');
const input = document.querySelector('#search-input');
const searchButton = document.querySelector('#search-button');
const status = document.querySelector('#status');
const workspace = document.querySelector('#workspace');
const results = document.querySelector('#results');
const resultCount = document.querySelector('#result-count');
const providerChip = document.querySelector('#provider-chip');
const jsonOutput = document.querySelector('#json-output');
const codeCaption = document.querySelector('#code-caption');
const copyButton = document.querySelector('#copy-button');
const typeButtons = [...document.querySelectorAll('.type-button')];
const viewButtons = [...document.querySelectorAll('.inspector-tab')];

let mediaType = 'movie';
let activeView = 'request';
let exchange = null;
let currentSearch = 0;

function setType(type) {
  mediaType = type;
  typeButtons.forEach((button) => {
    const selected = button.dataset.type === type;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  input.placeholder = type === 'game' ? 'Search a game title…' : type === 'tv' ? 'Search a TV series…' : 'Search a movie title…';
}

function setView(view) {
  activeView = view;
  viewButtons.forEach((button) => {
    const selected = button.dataset.view === view;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-selected', String(selected));
  });
  const labels = { request: 'Request sent to provider', response: 'Unchanged provider response', parsed: 'Normalized catalog fields' };
  codeCaption.textContent = labels[view];
  jsonOutput.textContent = exchange ? JSON.stringify(exchange[view], null, 2) : '{\n  "hint": "Run a search to inspect the API exchange"\n}';
  copyButton.disabled = !exchange;
}

function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function resultCard(item) {
  const card = el('article', 'result-card');
  const artwork = el('div', 'artwork');
  if (item.poster_url) {
    const image = document.createElement('img');
    image.src = item.poster_url;
    image.alt = '';
    image.loading = 'lazy';
    artwork.append(image);
  } else {
    artwork.classList.add('artwork-fallback');
    artwork.textContent = item.title.slice(0, 1).toUpperCase();
  }
  const body = el('div', 'result-body');
  const meta = el('div', 'result-meta');
  meta.append(el('span', '', `#${String(item.rank).padStart(2, '0')}`));
  meta.append(el('span', 'meta-divider', '·'));
  meta.append(el('span', '', item.year || 'Date unknown'));
  if (item.version_parent) meta.append(el('span', 'edition-pill', 'Edition'));
  const title = el('h3', 'result-title', item.title);
  const description = el('p', 'result-description', item.description || 'No description supplied by the provider.');
  body.append(meta, title, description);
  if (item.platforms?.length) body.append(el('div', 'platforms', item.platforms.slice(0, 4).join(' · ')));
  const foot = el('div', 'result-foot');
  foot.append(el('span', '', `ID ${item.id}`));
  if (item.provider_url) {
    const link = el('a', '', 'View source ↗');
    link.href = item.provider_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    foot.append(link);
  }
  body.append(foot);
  card.append(artwork, body);
  return card;
}

function renderResults(items) {
  results.replaceChildren();
  resultCount.textContent = String(items.length);
  if (!items.length) {
    results.append(el('div', 'empty-state', 'No matches found. Try another spelling or a shorter title.'));
    return;
  }
  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.append(resultCard(item)));
  results.append(fragment);
}

async function search() {
  const query = input.value.trim();
  if (!query) return;
  const searchId = ++currentSearch;
  searchButton.disabled = true;
  searchButton.textContent = 'Searching…';
  status.className = 'status loading';
  status.textContent = `Searching ${mediaType === 'game' ? 'IGDB' : 'TMDB'} for “${query}”…`;
  const params = new URLSearchParams({ type: mediaType, q: query });
  try {
    const response = await fetch(`/api/search?${params}`, { headers: { Accept: 'application/json' } });
    const payload = await response.json();
    if (searchId !== currentSearch) return;
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    exchange = payload;
    workspace.classList.remove('is-empty');
    providerChip.textContent = payload.provider;
    renderResults(payload.parsed);
    setView('request');
    status.className = 'status success';
    status.textContent = `${payload.parsed.length} ${payload.parsed.length === 1 ? 'match' : 'matches'} from ${payload.provider} for “${query}”`;
    window.history.replaceState({}, '', `?${params}`);
  } catch (error) {
    if (searchId !== currentSearch) return;
    status.className = 'status error';
    status.textContent = error.message;
  } finally {
    if (searchId === currentSearch) {
      searchButton.disabled = false;
      searchButton.innerHTML = 'Search <span aria-hidden="true">↗</span>';
    }
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  search();
});
typeButtons.forEach((button) => button.addEventListener('click', () => setType(button.dataset.type)));
viewButtons.forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
document.querySelectorAll('[data-example]').forEach((button) => button.addEventListener('click', () => {
  setType(button.dataset.type);
  input.value = button.dataset.example;
  search();
}));
copyButton.addEventListener('click', async () => {
  if (!exchange) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(exchange[activeView], null, 2));
    copyButton.textContent = 'Copied';
    window.setTimeout(() => { copyButton.textContent = 'Copy JSON'; }, 1800);
  } catch {
    copyButton.textContent = 'Copy unavailable';
  }
});

const initial = new URLSearchParams(window.location.search);
if (['movie', 'tv', 'game'].includes(initial.get('type'))) setType(initial.get('type'));
if (initial.get('q')) {
  input.value = initial.get('q').slice(0, 120);
  search();
}
