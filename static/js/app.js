/* ================================================
   NEXUS E-LIBRARY — Frontend Application
   ================================================ */

const API = '/api';
let currentUser = null;
let currentPage = 1;
let searchTimeout = null;
let selectedStars = 0;
let userBookmarks = new Set();
let adminUserSearchTimeout = null;
let currentPaper = null;
let currentPaperId = null;

// ── UTILS ──────────────────────────────────────

function getToken() {
  return localStorage.getItem('nexus_token');
}

function setToken(token) {
  localStorage.setItem('nexus_token', token);
}

function clearToken() {
  localStorage.removeItem('nexus_token');
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401) { logout(); return null; }
  return res;
}

function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = 'toast'; }, 3500);
}

function openModal(html, options = {}) {
  const modal = document.getElementById('modal');
  const body = document.getElementById('modal-body');
  const content = modal.querySelector('.modal-content');
  body.innerHTML = html;
  content.classList.toggle('resolve-large', Boolean(options.large));
  modal.classList.add('open');
}

function closeModalDirect() {
  const modal = document.getElementById('modal');
  const content = modal.querySelector('.modal-content');
  modal.classList.remove('open');
  content.classList.remove('resolve-large');
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function readApiResponse(res) {
  const contentType = (res.headers.get('content-type') || '').toLowerCase();
  if (contentType.includes('application/json')) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }

  try {
    const text = await res.text();
    return text ? { error: 'Server returned an unexpected response format.' } : null;
  } catch {
    return null;
  }
}

function getApiErrorMessage(payload, fallback) {
  if (payload && typeof payload.error === 'string' && payload.error.trim()) {
    return payload.error;
  }
  return fallback;
}

function resetInputs(container) {
  if (!container) return;
  const fields = container.querySelectorAll('input, textarea, select');
  fields.forEach(field => {
    if (field.tagName === 'SELECT') {
      if (field.multiple) {
        Array.from(field.options).forEach(opt => { opt.selected = false; });
      } else {
        field.selectedIndex = 0;
      }
      return;
    }

    if (field.type === 'checkbox' || field.type === 'radio') {
      field.checked = false;
      return;
    }

    field.value = '';
  });
}

function resetAuthForm(formId) {
  const form = document.getElementById(formId);
  if (form) resetInputs(form);
}

function resetReviewForm() {
  selectedStars = 0;
  const comment = document.getElementById('review-comment');
  if (comment) comment.value = '';
  document.querySelectorAll('.star-btn').forEach(btn => btn.classList.remove('active'));
}

function resetPageFields(pageId) {
  const page = document.getElementById(pageId);
  if (!page) return;
  resetInputs(page);

  if (pageId === 'page-papers') {
    const panel = document.getElementById('filter-panel');
    if (panel) panel.style.display = 'none';
  }

  if (pageId === 'page-upload') {
    const result = document.getElementById('upload-result');
    if (result) result.style.display = 'none';
  }

  if (pageId === 'page-paper-detail') {
    resetReviewForm();
  }
}

function setupAuthEnterSubmit() {
  ['login-email', 'login-password'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        login();
      }
    });
  });

  ['reg-name', 'reg-email', 'reg-password'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        register();
      }
    });
  });
}

function formatDate(d) {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function stars(n) {
  if (!n) return '<span style="color:var(--text-muted)">No ratings</span>';
  return '★'.repeat(Math.round(n)) + '☆'.repeat(5 - Math.round(n));
}

function enableMultiSelectToggle(select) {
  if (!select || select.dataset.multiToggle === '1') return;
  select.dataset.multiToggle = '1';
  select.addEventListener('mousedown', (event) => {
    if (event.target.tagName !== 'OPTION') return;
    event.preventDefault();
    const option = event.target;
    option.selected = !option.selected;
    select.focus();
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

function getActivityTitle(activity) {
  if (activity?.title) return activity.title;
  const type = (activity?.activity_type || '').toLowerCase();
  const labelMap = {
    review: 'Review added',
    unbookmark: 'Bookmark removed',
    delete_paper: 'Deleted paper',
    delete_user: 'Deleted user',
    plagiarism_approve: 'Plagiarism approved',
    plagiarism_reject: 'Plagiarism rejected'
  };
  return labelMap[type] || 'Unknown Paper';
}

function sanitizeFileName(name) {
  const base = (name || 'paper').toString().trim();
  const safe = base.replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '');
  return safe || 'paper';
}

function buildPaperText(paper) {
  const authors = Array.isArray(paper?.authors)
    ? paper.authors.map(a => `${a.author_name}${a.affiliation ? ` (${a.affiliation})` : ''}`).join('; ')
    : '';
  const categories = Array.isArray(paper?.categories)
    ? paper.categories.map(c => c.category_name).join(', ')
    : '';

  const lines = [
    `Title: ${paper?.title || 'Untitled Paper'}`,
    `Paper ID: ${paper?.paper_id || '—'}`,
    `Year: ${paper?.publication_year || '—'}`,
    `Uploaded By: ${paper?.uploader_name || '—'}`,
    `Authors: ${authors || '—'}`,
    `Categories: ${categories || '—'}`,
    `Views: ${paper?.views ?? '—'}`,
    `Downloads: ${paper?.downloads ?? '—'}`,
    '',
    'Abstract:',
    paper?.abstract || '—'
  ];

  return lines.join('\n');
}

// ── AUTH ───────────────────────────────────────

async function switchAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach((t, i) => {
    t.classList.toggle('active', (i === 0 && tab === 'login') || (i === 1 && tab === 'register'));
  });
  document.getElementById('login-form').style.display = tab === 'login' ? 'block' : 'none';
  document.getElementById('register-form').style.display = tab === 'register' ? 'block' : 'none';
  if (tab === 'login') {
    resetAuthForm('register-form');
  } else {
    resetAuthForm('login-form');
  }
  document.getElementById('auth-error').style.display = 'none';
}

async function login() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  if (!email || !password) return showError('auth-error', 'Please fill in all fields');

  try {
    const res = await fetch(API + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    const data = await readApiResponse(res);
    if (!res.ok) {
      return showError('auth-error', getApiErrorMessage(data, 'Login failed. Please try again.'));
    }

    if (!data || !data.token || !data.user) {
      return showError('auth-error', 'Login failed: invalid server response.');
    }

    setToken(data.token);
    currentUser = data.user;
    initApp();
  } catch {
    showError('auth-error', 'Unable to reach the server. Check backend and database connection.');
  }
}

async function register() {
  const name = document.getElementById('reg-name').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const role_id = parseInt(document.getElementById('reg-role').value);
  const institution_id = parseInt(document.getElementById('reg-institution').value) || null;

  if (!name || !email || !password) return showError('auth-error', 'Please fill in all fields');

  try {
    const res = await fetch(API + '/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password, role_id, institution_id })
    });

    const data = await readApiResponse(res);
    if (!res.ok) {
      return showError('auth-error', getApiErrorMessage(data, 'Registration failed. Please try again.'));
    }

    if (!data || !data.token || !data.user) {
      return showError('auth-error', 'Registration failed: invalid server response.');
    }

    setToken(data.token);
    currentUser = data.user;
    initApp();
  } catch {
    showError('auth-error', 'Unable to reach the server. Check backend and database connection.');
  }
}

function logout() {
  clearToken();
  currentUser = null;
  resetAuthForm('login-form');
  resetAuthForm('register-form');
  document.getElementById('auth-screen').style.display = 'flex';
  document.getElementById('main-app').style.display = 'none';
}

// ── APP INIT ───────────────────────────────────

async function bootstrap() {
  setupAuthEnterSubmit();

  // Load institutions for register form.
  try {
    const res = await fetch(API + '/users/institutions');
    if (res.ok) {
      const institutions = await res.json();
      const sel = document.getElementById('reg-institution');
      institutions.forEach(i => {
        const opt = document.createElement('option');
        opt.value = i.institution_id;
        opt.textContent = `${i.name} — ${i.location}`;
        sel.appendChild(opt);
      });
    }
  } catch {
    // Non-blocking on boot: auth should still work without institutions.
  }

  const token = getToken();
  if (!token) return;

  const meRes = await apiFetch('/auth/me');
  if (meRes && meRes.ok) {
    currentUser = await meRes.json();
    initApp();
  }
}

function initApp() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('main-app').style.display = 'flex';

  // Update UI for role
  document.getElementById('sidebar-name').textContent = currentUser.name;
  document.getElementById('sidebar-role').textContent = currentUser.role_name || ['', 'Admin', 'Researcher', 'Student'][currentUser.role_id];
  document.getElementById('user-avatar').textContent = currentUser.name.charAt(0).toUpperCase();
  document.getElementById('dash-name').textContent = currentUser.name.split(' ')[0];
  document.getElementById('today-date').textContent = new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  // Show/hide role-based nav
  document.querySelectorAll('.researcher-only').forEach(el => {
    el.style.display = [1, 2].includes(currentUser.role_id) ? 'flex' : 'none';
  });
  document.querySelectorAll('.admin-only').forEach(el => {
    el.style.display = currentUser.role_id === 1 ? 'flex' : 'none';
  });

  showPage('dashboard');
  loadBookmarkIds();
}

// ── NAVIGATION ─────────────────────────────────

function showPage(name) {
  const activePage = document.querySelector('.page.active');
  if (activePage && activePage.id !== `page-${name}`) {
    resetPageFields(activePage.id);
  }

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const page = document.getElementById(`page-${name}`);
  if (page) page.classList.add('active');

  const navItem = document.querySelector(`[data-page="${name}"]`);
  if (navItem) navItem.classList.add('active');

  // Load page data
  if (name === 'dashboard') loadDashboard();
  else if (name === 'papers') loadPapers();
  else if (name === 'bookmarks') loadBookmarks();
  else if (name === 'recommendations') loadRecommendations();
  else if (name === 'upload') loadUploadForm();
  else if (name === 'admin') loadAdmin();
}

function showAdminTab(tab) {
  showPage('admin');
  switchAdminTab(tab);
}

// ── DASHBOARD ──────────────────────────────────

async function loadDashboard() {
  // Load activity
  const actRes = await apiFetch('/users/activity');
  if (actRes && actRes.ok) {
    const activity = await actRes.json();
    const container = document.getElementById('activity-list');
    if (!activity.length) {
      container.innerHTML = '<div class="text-muted">No activity yet. Start exploring papers!</div>';
      return;
    }
    container.innerHTML = activity.slice(0, 8).map(a => {
      const activityType = (a.activity_type || 'activity').toLowerCase();
      const activityLabel = (a.activity_type || 'Activity').replace(/_/g, ' ');
      return `
      <div class="activity-item">
        <span class="activity-badge badge-${activityType}">${activityLabel}</span>
        <span class="activity-paper">${getActivityTitle(a)}</span>
        <span class="activity-date">${formatDate(a.activity_date)}</span>
      </div>
    `;
    }).join('');
  }

  // Admin stats
  if (currentUser.role_id === 1) {
    const statsRes = await apiFetch('/admin/stats');
    if (statsRes && statsRes.ok) {
      const stats = await statsRes.json();
      document.getElementById('stat-papers').textContent = stats.total_papers?.toLocaleString() || '—';
      document.getElementById('stat-views').textContent = stats.total_views?.toLocaleString() || '—';
      document.getElementById('stat-downloads').textContent = stats.total_downloads?.toLocaleString() || '—';
      document.getElementById('stat-flagged').textContent = stats.flagged_reports || '0';
    }
  } else {
    document.getElementById('stat-papers').textContent = '—';
    document.getElementById('stat-views').textContent = '—';
    document.getElementById('stat-downloads').textContent = '—';
    // Load papers count for non-admins
    const res = await apiFetch('/papers?per_page=1');
    if (res && res.ok) {
      const d = await res.json();
      document.getElementById('stat-papers').textContent = d.total?.toLocaleString() || '—';
    }
  }

  loadTopPapersWidget();
}

async function loadTopPapersWidget() {
  const topList = document.getElementById('top-papers-list');
  topList.innerHTML = '<div class="loading">Loading papers...</div>';

  const res = await apiFetch('/papers/top?limit=5');
  if (!res) {
    topList.innerHTML = '<div class="text-muted">Session expired. Please sign in again.</div>';
    return;
  }

  const data = await readApiResponse(res);
  if (!res.ok || !Array.isArray(data)) {
    topList.innerHTML = '<div class="text-muted">Unable to load top papers</div>';
    return;
  }

  topList.innerHTML = data.map(p => `
    <div class="top-paper-item">
      <span class="top-paper-title" onclick="viewPaper(${p.paper_id})">${p.title}</span>
      <span class="top-paper-views">👁 ${(p.views || 0).toLocaleString()}</span>
    </div>
  `).join('') || '<div class="text-muted">No data</div>';
}

// ── PAPERS ─────────────────────────────────────

function debounceSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(searchPapers, 400);
}

function toggleFilters() {
  const panel = document.getElementById('filter-panel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

function clearFilters() {
  ['search-keyword', 'search-author', 'search-category', 'search-year-from', 'search-year-to'].forEach(id => {
    document.getElementById(id).value = '';
  });
  searchPapers();
}

async function searchPapers(page = 1) {
  currentPage = page;
  const keyword = document.getElementById('search-keyword').value;
  const author = document.getElementById('search-author').value;
  const category = document.getElementById('search-category').value;
  const yearFrom = document.getElementById('search-year-from').value;
  const yearTo = document.getElementById('search-year-to').value;

  const params = new URLSearchParams({ page, per_page: 12 });
  if (keyword) params.append('keyword', keyword);
  if (author) params.append('author', author);
  if (category) params.append('category', category);
  if (yearFrom) params.append('year_from', yearFrom);
  if (yearTo) params.append('year_to', yearTo);

  const listEl = document.getElementById('papers-list');
  const paginationEl = document.getElementById('pagination');
  listEl.innerHTML = '<div class="loading">Searching...</div>';

  try {
    const res = await apiFetch(`/papers?${params}`);
    if (!res) {
      listEl.innerHTML = '<div class="error-msg">Session expired. Please sign in again.</div>';
      paginationEl.innerHTML = '';
      return;
    }

    const data = await readApiResponse(res);
    if (!res.ok) {
      listEl.innerHTML = `<div class="error-msg">${getApiErrorMessage(data, 'Failed to load papers')}</div>`;
      paginationEl.innerHTML = '';
      return;
    }

    const papers = Array.isArray(data?.papers) ? data.papers : [];
    renderPapers(papers, 'papers-list');
    renderPagination(data?.total || 0, data?.page || page, data?.per_page || 12);
  } catch {
    listEl.innerHTML = '<div class="error-msg">Unable to load papers right now.</div>';
    paginationEl.innerHTML = '';
  }
}

async function loadPapers(page = 1) {
  searchPapers(page);
}

function renderPapers(papers, containerId, extraInfo = '') {
  const container = document.getElementById(containerId);
  if (!papers.length) {
    container.innerHTML = `<div class="empty-state"><span class="empty-icon">◫</span><p>No papers found</p></div>`;
    return;
  }
  container.innerHTML = papers.map(p => `
    <div class="paper-card" onclick="viewPaper(${p.paper_id})">
      ${p.reason ? `<div class="rec-reason">${p.reason}</div>` : ''}
      <div class="paper-card-header">
        <div class="paper-title">${p.title}</div>
        <span class="paper-year">${p.publication_year || '—'}</span>
      </div>
      ${p.authors ? `<div class="paper-authors">by ${p.authors}</div>` : ''}
      ${p.abstract ? `<div class="paper-abstract">${p.abstract}</div>` : ''}
      <div class="paper-footer">
        <div class="paper-tags">
          ${(p.categories || '').split(',').filter(Boolean).map(c =>
            `<span class="tag">${c.trim()}</span>`
          ).join('')}
          ${p.flagged ? '<span class="flagged-badge">⚑ Flagged</span>' : ''}
        </div>
        <div class="paper-stats">
          ${p.views !== undefined ? `<span>👁 ${(p.views || 0).toLocaleString()}</span>` : ''}
          ${p.downloads !== undefined ? `<span>⬇ ${(p.downloads || 0).toLocaleString()}</span>` : ''}
        </div>
      </div>
    </div>
  `).join('');
}

function renderPagination(total, page, perPage) {
  const totalPages = Math.ceil(total / perPage);
  if (totalPages <= 1) { document.getElementById('pagination').innerHTML = ''; return; }
  const pag = document.getElementById('pagination');
  let html = '';
  if (page > 1) html += `<button class="page-btn" onclick="searchPapers(${page - 1})">← Prev</button>`;
  for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
    html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="searchPapers(${i})">${i}</button>`;
  }
  if (page < totalPages) html += `<button class="page-btn" onclick="searchPapers(${page + 1})">Next →</button>`;
  pag.innerHTML = html;
}

// ── PAPER DETAIL ───────────────────────────────

async function viewPaper(paperId) {
  showPageRaw('paper-detail');

  const container = document.getElementById('paper-detail-content');
  container.innerHTML = '<div class="loading">Loading paper details...</div>';

  try {
    const res = await apiFetch(`/papers/${paperId}`);
    if (!res) {
      container.innerHTML = '<div class="error-msg">Session expired. Please sign in again.</div>';
      return;
    }

    const data = await readApiResponse(res);
    if (!res.ok || !data) {
      container.innerHTML = `<div class="error-msg">${getApiErrorMessage(data, 'Failed to load paper')}</div>`;
      return;
    }

    const p = data;
    currentPaper = p;
    currentPaperId = paperId;

    const isBookmarked = userBookmarks.has(paperId);
    const plagClass = p.similarity_score >= 20 ? 'plag-high' : p.similarity_score >= 10 ? 'plag-medium' : 'plag-low';
    const isAdmin = currentUser.role_id === 1;

    container.innerHTML = `
    <div class="detail-layout">
      <div class="detail-main">
        <div class="detail-card">
          <div class="detail-title">${p.title}</div>
          <div class="detail-meta">
            <div class="meta-chip">📅 Published <span>${p.publication_year || '—'}</span></div>
            <div class="meta-chip">👁 <span>${(p.views || 0).toLocaleString()}</span> views</div>
            <div class="meta-chip">⬇ <span>${(p.downloads || 0).toLocaleString()}</span> downloads</div>
            ${p.avg_rating ? `<div class="meta-chip">★ <span>${p.avg_rating}/5</span></div>` : ''}
            <div class="meta-chip">Uploaded by <span>${p.uploader_name || '—'}</span></div>
          </div>
          ${p.abstract ? `
            <div class="section-title" style="margin-top:1rem">Abstract</div>
            <div class="detail-abstract">${p.abstract}</div>
          ` : ''}
          ${p.authors?.length ? `
            <div class="section-title" style="margin-top:1.25rem">Authors</div>
            <div class="paper-tags">
              ${p.authors.map(a => `<span class="tag">${a.author_name}${a.affiliation ? ` · ${a.affiliation}` : ''}</span>`).join('')}
            </div>
          ` : ''}
          ${p.categories?.length ? `
            <div class="section-title" style="margin-top:1.25rem">Categories</div>
            <div class="paper-tags">
              ${p.categories.map(c => `<span class="tag">${c.category_name}</span>`).join('')}
            </div>
          ` : ''}
        </div>

        <!-- Reviews -->
        <div class="detail-card">
          <div class="section-title">Reviews & Ratings</div>
          ${p.reviews?.length ? p.reviews.map(r => `
            <div class="review-item">
              <div class="review-header">
                <span class="reviewer-name">${r.reviewer_name}</span>
                <span class="stars">${stars(r.rating)}</span>
              </div>
              ${r.comment ? `<div class="review-comment">${r.comment}</div>` : ''}
            </div>
          `).join('') : '<div class="text-muted">No reviews yet. Be the first to review!</div>'}

          <div class="review-form">
            <div class="section-title">Add Your Review</div>
            <div class="star-selector" id="star-selector">
              ${[1,2,3,4,5].map(n => `<button class="star-btn" onclick="selectStar(${n}, ${paperId})" data-star="${n}">☆</button>`).join('')}
            </div>
            <div class="form-group">
              <textarea id="review-comment" rows="3" placeholder="Share your thoughts..."></textarea>
            </div>
            <button class="btn-secondary btn-sm" onclick="submitReview(${paperId})">Submit Review</button>
          </div>
        </div>

        <!-- Citations -->
        ${(p.cites?.length || p.cited_by?.length) ? `
        <div class="detail-card">
          <div class="section-title">Citation Network</div>
          ${p.cites?.length ? `
            <div style="margin-bottom:1rem">
              <div class="text-muted" style="margin-bottom:0.5rem;font-size:0.78rem">THIS PAPER CITES</div>
              ${p.cites.map(c => `
                <div class="citation-item" onclick="viewPaper(${c.paper_id})">
                  <div class="citation-title">${c.title}</div>
                  <div class="citation-year">${c.publication_year}</div>
                </div>
              `).join('')}
            </div>
          ` : ''}
          ${p.cited_by?.length ? `
            <div>
              <div class="text-muted" style="margin-bottom:0.5rem;font-size:0.78rem">CITED BY</div>
              ${p.cited_by.map(c => `
                <div class="citation-item" onclick="viewPaper(${c.paper_id})">
                  <div class="citation-title">${c.title}</div>
                  <div class="citation-year">${c.publication_year}</div>
                </div>
              `).join('')}
            </div>
          ` : ''}
        </div>
        ` : ''}
      </div>

      <div class="detail-sidebar">
        <!-- Actions -->
        <div class="sidebar-card">
          <div class="sidebar-card-title">Actions</div>
          <div class="action-group">
            <button class="action-btn ${isBookmarked ? 'bookmarked' : ''}" id="bookmark-btn-${paperId}"
              onclick="toggleBookmark(${paperId})">
              ${isBookmarked ? '◆ Bookmarked' : '◇ Bookmark Paper'}
            </button>
            <button class="action-btn" onclick="logDownload(${paperId})">
              ⬇ Download Paper
            </button>
            ${isAdmin ? `<button class="btn-danger" style="margin-top:0.5rem;width:100%" onclick='confirmDeletePaper(${paperId}, ${JSON.stringify(p.title)})'>⊗ Delete Paper</button>` : ''}
          </div>
        </div>

        <!-- Plagiarism -->
        ${p.similarity_score !== null && p.similarity_score !== undefined ? `
        <div class="sidebar-card">
          <div class="sidebar-card-title">Plagiarism Report</div>
          <div class="plag-info ${plagClass}">
            <div class="plag-score">${p.similarity_score}%</div>
            <div>
              <div style="font-size:0.82rem;font-weight:500">${p.flagged ? '⚑ Flagged for Review' : '✓ Below Threshold'}</div>
              <div style="font-size:0.72rem;opacity:0.7">Similarity Score</div>
            </div>
          </div>
          ${p.matched_paper_title ? `
            <div style="margin-top:0.65rem;font-size:0.78rem;color:var(--text-secondary)">
              Closest match:
              <span style="color:var(--accent);cursor:pointer" onclick="viewPaper(${p.matched_paper_id})">${p.matched_paper_title}</span>
              <span style="font-family:var(--font-mono);color:var(--text-muted)">(${p.matched_similarity_score}%)</span>
            </div>
          ` : ''}
        </div>
        ` : ''}

        <!-- Stats -->
        <div class="sidebar-card">
          <div class="sidebar-card-title">Statistics</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
            <div>
              <div class="stat-num" style="font-size:1.4rem">${(p.views || 0).toLocaleString()}</div>
              <div class="stat-label">Views</div>
            </div>
            <div>
              <div class="stat-num" style="font-size:1.4rem">${(p.downloads || 0).toLocaleString()}</div>
              <div class="stat-label">Downloads</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  } catch {
    container.innerHTML = '<div class="error-msg">Unable to load paper details right now.</div>';
  }
}

function showPageRaw(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const page = document.getElementById(`page-${name}`);
  if (page) page.classList.add('active');
}

// ── BOOKMARKS ──────────────────────────────────

async function loadBookmarkIds() {
  const res = await apiFetch('/users/bookmarks');
  if (res && res.ok) {
    const bookmarks = await res.json();
    userBookmarks = new Set(bookmarks.map(b => b.paper_id));
  }
}

async function loadBookmarks() {
  document.getElementById('bookmarks-list').innerHTML = '<div class="loading">Loading bookmarks...</div>';
  const res = await apiFetch('/users/bookmarks');
  if (!res || !res.ok) return;
  const bookmarks = await res.json();
  renderPapers(bookmarks, 'bookmarks-list');
}

async function toggleBookmark(paperId) {
  const isBookmarked = userBookmarks.has(paperId);
  const method = isBookmarked ? 'DELETE' : 'POST';
  const res = await apiFetch(`/users/bookmarks/${paperId}`, { method });
  if (res && res.ok) {
    if (isBookmarked) {
      userBookmarks.delete(paperId);
      showToast('Bookmark removed', 'info');
    } else {
      userBookmarks.add(paperId);
      showToast('Paper bookmarked! ◆', 'success');
    }
    // Update button
    const btn = document.getElementById(`bookmark-btn-${paperId}`);
    if (btn) {
      btn.className = `action-btn ${userBookmarks.has(paperId) ? 'bookmarked' : ''}`;
      btn.textContent = userBookmarks.has(paperId) ? '◆ Bookmarked' : '◇ Bookmark Paper';
    }
  }
}

// ── DOWNLOAD ───────────────────────────────────

async function logDownload(paperId) {
  const res = await apiFetch(`/papers/${paperId}/download`, { method: 'POST' });
  if (!res) return;

  const data = await readApiResponse(res);
  if (!res.ok) {
    showToast(getApiErrorMessage(data, 'Failed to download paper'), 'error');
    return;
  }

  const paper = currentPaperId === paperId ? currentPaper : null;
  if (!paper) {
    showToast('Download logged, but paper details are unavailable.', 'error');
    return;
  }

  const fileName = `${sanitizeFileName(paper.title)}_${paper.publication_year || 'paper'}.txt`;
  const content = buildPaperText(paper);
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);

  showToast('Download started', 'success');
  if (document.getElementById('page-dashboard')?.classList.contains('active')) {
    loadDashboard();
  }
}

// ── REVIEWS ────────────────────────────────────

function selectStar(n, paperId) {
  selectedStars = n;
  document.querySelectorAll('#star-selector .star-btn').forEach((btn, i) => {
    btn.textContent = i < n ? '★' : '☆';
    btn.classList.toggle('active', i < n);
  });
}

async function submitReview(paperId) {
  if (!selectedStars) return showToast('Please select a rating', 'error');
  const comment = document.getElementById('review-comment').value;
  const res = await apiFetch(`/papers/${paperId}/review`, {
    method: 'POST',
    body: JSON.stringify({ rating: selectedStars, comment })
  });
  if (res && res.ok) {
    showToast('Review submitted! Thank you.', 'success');
    viewPaper(paperId); // Refresh
  } else {
    const d = await res.json();
    showToast(d.error || 'Failed to submit review', 'error');
  }
}

// ── RECOMMENDATIONS ────────────────────────────

async function loadRecommendations() {
  document.getElementById('rec-list').innerHTML = '<div class="loading">Generating personalized recommendations...</div>';

  try {
    const res = await apiFetch('/recommendations');
    if (!res) {
      document.getElementById('rec-list').innerHTML = '<div class="error-msg">Session expired. Please sign in again.</div>';
      return;
    }

    const data = await readApiResponse(res);
    if (!res.ok) {
      document.getElementById('rec-list').innerHTML = `<div class="error-msg">${getApiErrorMessage(data, 'Failed to load recommendations')}</div>`;
      return;
    }

    renderPapers(data?.recommendations || [], 'rec-list');
  } catch {
    document.getElementById('rec-list').innerHTML = '<div class="error-msg">Unable to generate recommendations right now.</div>';
  }
}

// ── UPLOAD ─────────────────────────────────────

async function loadUploadForm() {
  const yearInput = document.getElementById('up-year');
  const currentYear = new Date().getFullYear();
  if (yearInput) {
    yearInput.max = currentYear;
    yearInput.placeholder = currentYear;
    if (parseInt(yearInput.value, 10) > currentYear) yearInput.value = '';
  }

  // Load authors
  const authRes = await apiFetch('/papers/authors');
  if (authRes && authRes.ok) {
    const authors = await authRes.json();
    const sel = document.getElementById('up-authors');
    sel.innerHTML = authors.map(a => `<option value="${a.author_id}">${a.author_name} · ${a.affiliation || ''}</option>`).join('');
    enableMultiSelectToggle(sel);
  }

  // Load categories
  const catRes = await apiFetch('/papers/categories');
  if (catRes && catRes.ok) {
    const cats = await catRes.json();
    const sel = document.getElementById('up-categories');
    sel.innerHTML = cats.map(c => `<option value="${c.category_id}">${c.category_name}</option>`).join('');
    enableMultiSelectToggle(sel);
  }

  // Load citation candidates
  const citeRes = await apiFetch('/papers/citations');
  if (citeRes && citeRes.ok) {
    const cites = await citeRes.json();
    const sel = document.getElementById('up-citations');
    sel.innerHTML = cites.map(p => `
      <option value="${p.paper_id}">${p.title}${p.publication_year ? ` · ${p.publication_year}` : ''}</option>
    `).join('');
    enableMultiSelectToggle(sel);
  }

  document.getElementById('upload-result').style.display = 'none';
}

async function uploadPaper() {
  const title = document.getElementById('up-title').value.trim();
  const abstract = document.getElementById('up-abstract').value.trim();
  const publication_year = parseInt(document.getElementById('up-year').value, 10);
  const currentYear = new Date().getFullYear();

  if (!title || !publication_year) return showToast('Title and year are required', 'error');
  if (publication_year > currentYear) {
    return showToast(`Publication year must be ${currentYear} or earlier`, 'error');
  }
  if (publication_year < 1900) return showToast('Publication year must be 1900 or later', 'error');

  const authorSel = document.getElementById('up-authors');
  const author_ids = Array.from(authorSel.selectedOptions).map(o => parseInt(o.value));
  const catSel = document.getElementById('up-categories');
  const category_ids = Array.from(catSel.selectedOptions).map(o => parseInt(o.value));
  const citeSel = document.getElementById('up-citations');
  const citation_ids = Array.from(citeSel?.selectedOptions || []).map(o => parseInt(o.value));

  const new_author_name = document.getElementById('new-author-name').value.trim();
  const new_author_affiliation = document.getElementById('new-author-affil').value.trim();
  const new_category_name = document.getElementById('new-category-name').value.trim();
  const new_category_description = document.getElementById('new-category-desc').value.trim();

  if (new_author_affiliation && !new_author_name) {
    return showToast('Author name is required when adding an affiliation', 'error');
  }
  if (new_author_name && !new_author_affiliation) {
    return showToast('Affiliation is required for a new author', 'error');
  }
  if (!author_ids.length && !new_author_name) {
    return showToast('Please select at least one author or add a new author', 'error');
  }
  if (new_category_description && !new_category_name) {
    return showToast('Category name is required when adding a description', 'error');
  }
  if (!category_ids.length && !new_category_name) {
    return showToast('Please select at least one category or add a new category', 'error');
  }

  const res = await apiFetch('/papers', {
    method: 'POST',
    body: JSON.stringify({
      title,
      abstract,
      publication_year,
      author_ids,
      category_ids,
      citation_ids,
      new_author_name,
      new_author_affiliation,
      new_category_name,
      new_category_description
    })
  });

  const data = await res.json();
  if (!res.ok) return showToast(data.error || 'Upload failed', 'error');

  const plag = data.plagiarism;
  const resultDiv = document.getElementById('upload-result');
  resultDiv.style.display = 'block';

  if (plag.flagged) {
    const matchInfo = plag.matched_paper_title
      ? `<br>Closest match: <strong>${plag.matched_paper_title}</strong> (${plag.matched_similarity_score}%)`
      : '';

    resultDiv.className = 'plag-result plag-high';
    resultDiv.innerHTML = `
      <strong>⚑ Plagiarism Alert</strong><br>
      Similarity score: <strong>${plag.similarity_score}%</strong> — Paper has been flagged for admin review.
      It has been submitted but requires approval.${matchInfo}
    `;
    showToast(`Paper submitted but flagged (${plag.similarity_score}% similarity)`, 'error');
  } else {
    const matchInfo = plag.matched_paper_title
      ? `<br>Closest match checked: <strong>${plag.matched_paper_title}</strong> (${plag.matched_similarity_score}%)`
      : '';
    const citedNote = plag.citation_match
      ? '<br><span class="text-muted">Closest match is cited, so it was not flagged.</span>'
      : '';

    resultDiv.className = 'plag-result plag-low';
    resultDiv.innerHTML = `
      <strong>✓ Paper Uploaded Successfully!</strong><br>
      Plagiarism check passed. Similarity score: <strong>${plag.similarity_score}%</strong>${matchInfo}${citedNote}
    `;
    showToast('Paper uploaded successfully!', 'success');
  }

  // Reset form
  ['up-title', 'up-abstract', 'up-year', 'new-author-name', 'new-author-affil', 'new-category-name', 'new-category-desc'].forEach(id => {
    document.getElementById(id).value = '';
  });
  [authorSel, catSel, citeSel].forEach(sel => {
    if (!sel) return;
    Array.from(sel.options).forEach(o => { o.selected = false; });
  });
}

// ── ADMIN ──────────────────────────────────────

function loadAdmin() {
  loadAdminStats();
  switchAdminTab('overview');
}

async function loadAdminStats() {
  const res = await apiFetch('/admin/stats');
  if (!res || !res.ok) return;
  const stats = await res.json();

  const grid = document.getElementById('admin-stats-grid');
  grid.innerHTML = `
    <div class="stat-card"><div class="stat-num">${stats.total_papers}</div><div class="stat-label">Total Papers</div></div>
    <div class="stat-card"><div class="stat-num">${stats.total_users}</div><div class="stat-label">Total Users</div></div>
    <div class="stat-card"><div class="stat-num">${stats.total_views?.toLocaleString()}</div><div class="stat-label">Total Views</div></div>
    <div class="stat-card"><div class="stat-num">${stats.total_downloads?.toLocaleString()}</div><div class="stat-label">Downloads</div></div>
    <div class="stat-card"><div class="stat-num flagged-num">${stats.flagged_reports}</div><div class="stat-label">Flagged Reports</div></div>
  `;
}

function switchAdminTab(tab) {
  const sectionMap = {
    overview: 'admin-overview',
    users: 'admin-users',
    plagiarism: 'admin-plagiarism'
  };
  const nextSectionId = sectionMap[tab] || 'admin-overview';
  const currentSection = document.querySelector('.admin-section.active');
  if (currentSection && currentSection.id !== nextSectionId) {
    resetInputs(currentSection);
  }

  document.querySelectorAll('.admin-tab').forEach(t => {
    t.classList.toggle('active', t.textContent.toLowerCase().includes(tab.toLowerCase()) ||
      (tab === 'overview' && t.textContent === 'Overview') ||
      (tab === 'users' && t.textContent === 'Users') ||
      (tab === 'plagiarism' && t.textContent === 'Plagiarism Reports'));
  });
  document.querySelectorAll('.admin-section').forEach(s => s.classList.remove('active'));

  if (tab === 'overview') {
    document.getElementById('admin-overview').classList.add('active');
    document.getElementById('admin-overview').style.display = 'block';
    document.getElementById('admin-users').style.display = 'none';
    document.getElementById('admin-plagiarism').style.display = 'none';
    loadAdminStats();
  } else if (tab === 'users') {
    document.getElementById('admin-overview').style.display = 'none';
    document.getElementById('admin-users').style.display = 'block';
    document.getElementById('admin-plagiarism').style.display = 'none';
    loadAdminUsers();
  } else if (tab === 'plagiarism') {
    document.getElementById('admin-overview').style.display = 'none';
    document.getElementById('admin-users').style.display = 'none';
    document.getElementById('admin-plagiarism').style.display = 'block';
    loadPlagiarismReports();
  }
}

async function loadAdminUsers() {
  const container = document.getElementById('admin-users-table');
  container.innerHTML = '<div class="loading">Loading users...</div>';
  const roleFilter = document.getElementById('admin-user-role')?.value || 'all';
  const searchQuery = document.getElementById('admin-user-search')?.value.trim() || '';
  const params = new URLSearchParams();
  if (roleFilter && roleFilter !== 'all') params.append('role', roleFilter);
  if (searchQuery) params.append('q', searchQuery);

  const res = await apiFetch(`/admin/users${params.toString() ? `?${params}` : ''}`);
  if (!res) {
    container.innerHTML = '<div class="error-msg">Session expired. Please sign in again.</div>';
    return;
  }
  if (!res.ok) {
    const d = await readApiResponse(res);
    container.innerHTML = `<div class="error-msg">${getApiErrorMessage(d, 'Failed to load users')}</div>`;
    return;
  }
  const users = await res.json();

  if (!users.length) {
    container.innerHTML = '<div class="empty-state"><span class="empty-icon">👤</span><p>No users found</p></div>';
    return;
  }

  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>ID</th><th>Name</th><th>Email</th><th>Role</th><th>Institution</th><th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${users.map(u => `
          <tr>
            <td><span style="font-family:var(--font-mono);color:var(--text-muted)">#${u.user_id}</span></td>
            <td>${u.name}</td>
            <td style="font-family:var(--font-mono);font-size:0.8rem">${u.email}</td>
            <td><span class="role-badge role-${u.role_id}">${u.role_name}</span></td>
            <td>${u.institution_name || '—'}</td>
            <td>${u.user_id !== currentUser.user_id ? `<button class="btn-danger btn-sm" onclick='confirmDeleteUser(${u.user_id}, ${JSON.stringify(u.name)}, ${JSON.stringify(u.email)})'>Delete</button>` : '<span class="text-muted">You</span>'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function debounceAdminUserSearch() {
  clearTimeout(adminUserSearchTimeout);
  adminUserSearchTimeout = setTimeout(() => loadAdminUsers(), 350);
}

function clearAdminUserFilters() {
  const roleSel = document.getElementById('admin-user-role');
  const searchInput = document.getElementById('admin-user-search');
  if (roleSel) roleSel.value = 'all';
  if (searchInput) searchInput.value = '';
  loadAdminUsers();
}

function confirmDeleteUser(userId, name, email) {
  const displayName = name || 'this user';
  const displayEmail = email ? `<div class="confirm-email">${email}</div>` : '';
  const html = `
    <div class="confirm-modal">
      <div class="confirm-title">Delete User</div>
      <div class="confirm-body">Are you sure you want to delete <strong>${displayName}</strong>? This action cannot be undone.</div>
      ${displayEmail}
      <div class="confirm-actions">
        <button class="btn-ghost" onclick="closeModalDirect()">Cancel</button>
        <button class="btn-danger" onclick="deleteUser(${userId})">Delete User</button>
      </div>
    </div>
  `;
  openModal(html);
}

async function deleteUser(userId) {
  const res = await apiFetch(`/admin/users/${userId}`, { method: 'DELETE' });
  if (!res) return;
  const d = await readApiResponse(res);
  if (!res.ok) return showToast(getApiErrorMessage(d, 'Failed to delete user'), 'error');

  closeModalDirect();
  showToast('User deleted', 'success');
  loadAdminUsers();
}

async function loadPlagiarismReports() {
  const flaggedOnly = document.getElementById('flagged-only')?.checked || false;
  const container = document.getElementById('plagiarism-table');
  container.innerHTML = '<div class="loading">Loading reports...</div>';

  const res = await apiFetch(`/admin/plagiarism?flagged=${flaggedOnly}`);
  if (!res) {
    container.innerHTML = '<div class="error-msg">Session expired. Please sign in again.</div>';
    return;
  }
  if (!res.ok) {
    const d = await readApiResponse(res);
    container.innerHTML = `<div class="error-msg">${getApiErrorMessage(d, 'Failed to load reports')}</div>`;
    return;
  }
  const reports = await res.json();

  if (!reports.length) {
    container.innerHTML = '<div class="empty-state"><span class="empty-icon">✓</span><p>No plagiarism reports found</p></div>';
    return;
  }

  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr><th>ID</th><th>Paper</th><th>Matched With</th><th>Uploaded By</th><th>Similarity</th><th>Status</th><th>Action</th></tr>
      </thead>
      <tbody>
        ${reports.map(r => {
          const cls = r.similarity_score >= 20 ? 'text-danger' : r.similarity_score >= 10 ? '' : 'text-success';
          const matchedWith = r.matched_paper_title
            ? `<span style="cursor:pointer;color:var(--accent)" onclick="viewPaper(${r.matched_paper_id})">${r.matched_paper_title}</span> <span style="font-family:var(--font-mono);color:var(--text-muted)">(${r.matched_similarity_score}%)</span>`
            : '<span class="text-muted">—</span>';
          return `
            <tr>
              <td><span style="font-family:var(--font-mono);color:var(--text-muted)">#${r.report_id}</span></td>
              <td><span style="cursor:pointer;color:var(--accent)" onclick="viewPaper(${r.paper_id})">${r.title}</span></td>
              <td>${matchedWith}</td>
              <td>${r.uploaded_by}</td>
              <td class="${cls}" style="font-family:var(--font-mono)">${r.similarity_score}%</td>
              <td>${r.flagged ? '<span class="flagged-badge">⚑ Flagged</span>' : '<span style="color:var(--success);font-size:0.8rem">✓ Clear</span>'}</td>
              <td>${r.flagged ? `<button class="btn-secondary btn-sm" onclick="resolveReport(${r.report_id})">Resolve</button>` : '—'}</td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
}

function renderPlagiarismPaperCard(paper, heading, extraMeta = '') {
  if (!paper) {
    return `
      <div class="resolve-card">
        <div class="section-title">${heading}</div>
        <div class="text-muted">No match found.</div>
      </div>
    `;
  }

  const authors = paper.authors?.length
    ? paper.authors.map(a => `<span class="tag">${a.author_name}${a.affiliation ? ` · ${a.affiliation}` : ''}</span>`).join('')
    : '<span class="text-muted">—</span>';
  const categories = paper.categories?.length
    ? paper.categories.map(c => `<span class="tag">${c.category_name}</span>`).join('')
    : '<span class="text-muted">—</span>';
  const abstract = paper.abstract
    ? `<div class="resolve-abstract">${paper.abstract}</div>`
    : '<div class="text-muted">No abstract available.</div>';

  return `
    <div class="resolve-card">
      <div class="section-title">${heading}</div>
      <div class="resolve-paper-title">${paper.title || 'Untitled Paper'}</div>
      <div class="resolve-meta">
        <div class="meta-chip">ID <span>#${paper.paper_id}</span></div>
        ${paper.publication_year ? `<div class="meta-chip">Year <span>${paper.publication_year}</span></div>` : ''}
        ${paper.uploader_name ? `<div class="meta-chip">Uploader <span>${paper.uploader_name}</span></div>` : ''}
        ${extraMeta}
      </div>
      ${abstract}
      <div class="resolve-row">
        <div class="resolve-label">Authors</div>
        <div class="paper-tags">${authors}</div>
      </div>
      <div class="resolve-row">
        <div class="resolve-label">Categories</div>
        <div class="paper-tags">${categories}</div>
      </div>
    </div>
  `;
}

async function resolveReport(reportId) {
  const res = await apiFetch(`/admin/plagiarism/${reportId}`);
  if (!res) return;

  const data = await readApiResponse(res);
  if (!res.ok || !data) {
    showToast(getApiErrorMessage(data, 'Failed to load report details'), 'error');
    return;
  }

  const matchMeta = data.match?.similarity_score !== undefined
    ? `<div class="meta-chip">Similarity <span>${data.match.similarity_score}%</span></div>`
    : '';
  const flaggedCard = renderPlagiarismPaperCard(data.paper, 'Flagged Paper');
  const matchCard = renderPlagiarismPaperCard(data.match, 'Closest Match', matchMeta);

  const html = `
    <div class="resolve-modal">
      <div class="resolve-header">
        <div>
          <div class="resolve-title">Resolve Plagiarism Report #${data.report_id}</div>
          <div class="resolve-sub">Similarity ${data.similarity_score}% · ${data.flagged ? 'Flagged' : 'Clear'}</div>
        </div>
        <button class="btn-ghost btn-sm" onclick="closeModalDirect()">Close</button>
      </div>
      <div class="resolve-grid">
        ${flaggedCard}
        ${matchCard}
      </div>
      <div class="resolve-note">Approving clears the report. Rejecting permanently deletes the paper and related data.</div>
      <div class="resolve-actions">
        <button class="btn-secondary" onclick="submitResolveReport(${data.report_id}, 'approve')">Approve</button>
        <button class="btn-danger" onclick="submitResolveReport(${data.report_id}, 'reject')">Reject & Delete</button>
      </div>
    </div>
  `;

  openModal(html, { large: true });
}

async function submitResolveReport(reportId, action) {
  const res = await apiFetch(`/admin/plagiarism/${reportId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ action })
  });
  if (!res) return;

  const data = await readApiResponse(res);
  if (!res.ok) {
    showToast(getApiErrorMessage(data, 'Failed to resolve report'), 'error');
    return;
  }

  closeModalDirect();
  showToast(action === 'approve' ? 'Paper approved' : 'Paper rejected and deleted', 'success');
  loadPlagiarismReports();
  loadAdminStats();
}

function confirmDeletePaper(paperId, title) {
  const displayTitle = title || 'this paper';
  const html = `
    <div class="confirm-modal">
      <div class="confirm-title">Delete Paper</div>
      <div class="confirm-body">Are you sure you want to permanently delete <strong>${displayTitle}</strong>? This action cannot be undone.</div>
      <div class="confirm-actions">
        <button class="btn-ghost" onclick="closeModalDirect()">Cancel</button>
        <button class="btn-danger" onclick="deletePaper(${paperId})">Delete Paper</button>
      </div>
    </div>
  `;
  openModal(html);
}

async function deletePaper(paperId) {
  const res = await apiFetch(`/papers/${paperId}`, { method: 'DELETE' });
  if (!res) return;

  const data = await readApiResponse(res);
  if (!res.ok) {
    showToast(getApiErrorMessage(data, 'Failed to delete paper'), 'error');
    return;
  }

  closeModalDirect();
  showToast('Paper deleted', 'success');
  showPage('papers');
}

// ── MODAL ──────────────────────────────────────

function closeModal(e) {
  if (e.target === document.getElementById('modal')) {
    closeModalDirect();
  }
}

// ── BOOT ───────────────────────────────────────
window.switchAuthTab = switchAuthTab;
window.login = login;
window.register = register;

bootstrap();
