const BASE = `http://${window.location.hostname}:8000/api`

function authHeaders() {
  const token = localStorage.getItem('docagent_token')
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function handleResponse(res) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    const detail = err.detail || 'Request failed'
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export async function signup(email, password) {
  const res = await fetch(`${BASE}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  // Don't use handleResponse for auth endpoints — 401 here means bad credentials, not expired token
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || 'Signup failed')
  }
  return res.json()
}

export async function login(email, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || 'Login failed')
  }
  return res.json()
}

// ── Utilities ─────────────────────────────────────────────────────────────────

/** Compute deterministic doc_id matching the backend: sha256(filename:size)[:16] */
export async function computeDocId(file) {
  const data = new TextEncoder().encode(`${file.name}:${file.size}`)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
  return hashHex.slice(0, 16)
}

// ── Documents ──────────────────────────────────────────────────────────────────

export async function uploadDocument(file, docType = 'general') {
  const token = localStorage.getItem('docagent_token')
  if (!token) throw new Error('Not authenticated — please log in')

  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  const res = await fetch(`${BASE}/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  return handleResponse(res)
}

export async function listDocuments() {
  const res = await fetch(`${BASE}/documents`, { headers: authHeaders() })
  return handleResponse(res)
}

export async function deleteDocument(docId) {
  const res = await fetch(`${BASE}/documents/${docId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  return handleResponse(res)
}

// ── Ask ────────────────────────────────────────────────────────────────────────

export async function ask(question, docIds, conversationHistory = []) {
  const res = await fetch(`${BASE}/ask`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      question,
      doc_ids: docIds,
      conversation_history: conversationHistory,
    }),
  })
  return handleResponse(res)
}
