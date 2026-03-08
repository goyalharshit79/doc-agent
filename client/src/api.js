// In production: set VITE_API_URL to your Cloud Run backend URL (e.g. https://docagent-xxx-uc.a.run.app/api)
// In development: falls back to localhost:8000
const BASE = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000/api`

// ── Structured error codes from backend ────────────────────────────────────
// Guards return JSON detail: { code, message, current, limit, plan }
// We parse these and attach them to the Error object for UI-level handling.

function friendlyError(err, context = 'general') {
  const msg = (err?.message || err || '').toLowerCase()

  // Network / connectivity errors
  if (msg.includes('failed to fetch') || msg.includes('networkerror') || msg.includes('network')
      || msg.includes('err_connection') || msg.includes('load failed')) {
    return 'Unable to connect. Please check your internet connection and try again.'
  }

  // Auth-specific friendly messages
  if (context === 'login' || context === 'signup') {
    if (msg.includes('invalid') || msg.includes('credentials') || msg.includes('unauthorized') || msg.includes('401')) {
      return 'Incorrect email or password. Please try again.'
    }
    if (msg.includes('already') || msg.includes('exists') || msg.includes('duplicate')) {
      return 'An account with this email already exists. Try signing in instead.'
    }
    if (msg.includes('weak') || msg.includes('password') || msg.includes('short')) {
      return 'Your password is too weak. Please use at least 8 characters.'
    }
    if (msg.includes('rate') || msg.includes('limit') || msg.includes('429')) {
      return 'Too many attempts. Please wait a moment and try again.'
    }
    return context === 'signup'
      ? 'Could not create your account. Please try again.'
      : 'Could not sign you in. Please try again.'
  }

  // Generic fallback
  return 'Something went wrong. Please try again.'
}

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

    // If detail is a structured object (from guards), create a rich error
    if (typeof detail === 'object' && detail.code) {
      const error = new Error(detail.message || 'Request failed')
      error.code = detail.code            // e.g. "DOCUMENT_LIMIT", "QUERY_LIMIT"
      error.current = detail.current
      error.limit = detail.limit
      error.plan = detail.plan
      error.status = res.status
      throw error
    }

    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

// ── Token Refresh Logic ────────────────────────────────────────────────────────

let isRefreshing = false
let refreshPromise = null

async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('docagent_refresh_token')
  if (!refreshToken) throw new Error('No refresh token available')

  const res = await fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  })

  if (!res.ok) {
    localStorage.removeItem('docagent_token')
    localStorage.removeItem('docagent_refresh_token')
    window.dispatchEvent(new Event('docagent:session_expired'))
    throw new Error('Session expired. Please log in again.')
  }

  const data = await res.json()
  localStorage.setItem('docagent_token', data.access_token)
  if (data.refresh_token) {
    localStorage.setItem('docagent_refresh_token', data.refresh_token)
  }
  return data.access_token
}

async function authFetch(url, options = {}, timeoutMs = 120_000) {
  // Always inject the latest token before making the request
  const setTokenHeader = (opts) => {
    const token = localStorage.getItem('docagent_token')
    if (token) {
      opts.headers = {
        ...opts.headers,
        Authorization: `Bearer ${token}`
      }
    }
    return opts
  }

  // Abort controller — prevents fetch from hanging forever
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    let finalOptions = setTokenHeader({ ...options, signal: controller.signal })
    let res = await fetch(url, finalOptions)

    if (res.status === 401) {
      // If another request is currently refreshing the token, wait for it to finish
      if (!isRefreshing) {
        isRefreshing = true
        refreshPromise = refreshAccessToken().finally(() => {
          isRefreshing = false
          refreshPromise = null
        })
      }

      try {
        await refreshPromise
        // Retry the original request with the new token
        finalOptions = setTokenHeader({ ...options, signal: controller.signal })
        res = await fetch(url, finalOptions)
      } catch (refreshErr) {
        throw refreshErr // The session expired event has been dispatched
      }
    }

    return handleResponse(res)
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out. The server is still processing — please try again in a moment.')
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export async function signup(email, password) {
  try {
    const res = await fetch(`${BASE}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Signup failed' }))
      throw new Error(err.detail || 'Signup failed')
    }
    return res.json()
  } catch (e) {
    throw new Error(friendlyError(e, 'signup'))
  }
}

export async function login(email, password) {
  try {
    const res = await fetch(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Login failed' }))
      throw new Error(err.detail || 'Login failed')
    }
    return res.json()
  } catch (e) {
    throw new Error(friendlyError(e, 'login'))
  }
}

// ── Forgot / Reset Password ──────────────────────────────────────────────────

export async function forgotPassword(email) {
  const res = await fetch(`${BASE}/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  return res.json()
}

export async function resetPassword({ accessToken, tokenHash, newPassword }) {
  const payload = { new_password: newPassword }
  if (tokenHash) payload.token_hash = tokenHash
  else if (accessToken) payload.access_token = accessToken

  const res = await fetch(`${BASE}/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Reset failed' }))
    throw new Error(err.detail || 'Password reset failed')
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
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)

  // 5 min — large docs need time for parsing + batched embeddings + GCP retries
  return authFetch(`${BASE}/upload`, {
    method: 'POST',
    body: form,
  }, 300_000)
}

export async function listDocuments() {
  return authFetch(`${BASE}/documents`, {
    headers: { 'Content-Type': 'application/json' }
  })
}

export async function deleteDocument(docId) {
  return authFetch(`${BASE}/documents/${docId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  })
}

// ── Ask ────────────────────────────────────────────────────────────────────────

export async function ask(question, docIds, conversationHistory = []) {
  // 3 min — RAG pipeline includes retrieval + reranking + LLM generation + GCP retries
  return authFetch(`${BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      doc_ids: docIds,
      conversation_history: conversationHistory,
    }),
  }, 180_000)
}

// ── Usage / Billing ─────────────────────────────────────────────────────────────

export async function getUsage() {
  return authFetch(`${BASE}/usage`, {
    headers: { 'Content-Type': 'application/json' },
  })
}

export async function createSubscription(email) {
  return authFetch(`${BASE}/billing/subscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
}

// ── Admin ───────────────────────────────────────────────────────────────────────

export async function getAdminUsers() {
  return authFetch(`${BASE}/admin/users`, {
    headers: { 'Content-Type': 'application/json' },
  })
}

export async function updateAdminUser(userId, data) {
  return authFetch(`${BASE}/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function deleteAdminUser(userId) {
  return authFetch(`${BASE}/admin/users/${userId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  })
}
