import React, { useState } from 'react'
import { Eye, EyeOff, MailCheck } from 'lucide-react'
import { login, signup } from '../api'

export default function AuthPage({ onAuth }) {
  const [mode, setMode]               = useState('login')
  const [email, setEmail]             = useState('')
  const [password, setPassword]       = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError]             = useState(null)
  const [loading, setLoading]         = useState(false)
  const [notice, setNotice]           = useState(null)

  const handleSubmit = async () => {
    setError(null)
    setNotice(null)
    if (!email || !password) { setError('Email and password are required.'); return }

    setLoading(true)
    try {
      if (mode === 'signup') {
        const res = await signup(email, password)
        if (res.access_token === 'pending_email_confirmation') {
          setNotice('Check your email to confirm your account, then log in.')
          setMode('login')
        } else {
          localStorage.setItem('docagent_token', res.access_token)
          onAuth({ token: res.access_token, userId: res.user_id, email: res.email })
        }
      } else {
        const res = await login(email, password)
        localStorage.setItem('docagent_token', res.access_token)
        onAuth({ token: res.access_token, userId: res.user_id, email: res.email })
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => { if (e.key === 'Enter') handleSubmit() }

  return (
    <div className="auth-root">
      <div className="auth-grain" />

      <div className="auth-card" style={{ animationDelay: '0.05s' }}>

        {/* Logo */}
        <div className="auth-logo">
          <span className="logo-mark">D</span>
          <span className="logo-text">oc<em>Agent</em></span>
        </div>

        <p className="auth-tagline">
          {mode === 'login' ? 'Welcome back.' : 'Create your account.'}
        </p>

        {/* Mode toggle */}
        <div className="auth-toggle">
          <button
            className={`auth-toggle-btn${mode === 'login' ? ' auth-toggle-btn--active' : ''}`}
            onClick={() => { setMode('login'); setError(null); setNotice(null) }}
          >
            Sign in
          </button>
          <button
            className={`auth-toggle-btn${mode === 'signup' ? ' auth-toggle-btn--active' : ''}`}
            onClick={() => { setMode('signup'); setError(null); setNotice(null) }}
          >
            Create account
          </button>
        </div>

        {/* Fields */}
        <div className="auth-fields">
          <div className="auth-field">
            <label className="auth-label">Email</label>
            <input
              className="auth-input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onKeyDown={handleKey}
              autoFocus
            />
          </div>

          <div className="auth-field">
            <label className="auth-label">Password</label>
            <div className="auth-input-wrap">
              <input
                className="auth-input auth-input--has-toggle"
                type={showPassword ? 'text' : 'password'}
                placeholder={mode === 'signup' ? 'Min. 8 characters' : '••••••••'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                onKeyDown={handleKey}
              />
              <button
                type="button"
                className="auth-password-toggle"
                onClick={() => setShowPassword(prev => !prev)}
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        </div>

        {/* Feedback */}
        {error && <p className="auth-error">{error}</p>}
        {notice && (
          <div className="auth-notice auth-notice--prominent">
            <div className="auth-notice-icon">
              <MailCheck size={20} />
            </div>
            <div>
              <p className="auth-notice-title">Verification required</p>
              <p className="auth-notice-text">{notice}</p>
            </div>
          </div>
        )}

        {/* Submit */}
        <button
          className="auth-submit"
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading
            ? <span className="auth-spinner" />
            : mode === 'login' ? 'Sign in' : 'Create account'
          }
        </button>

      </div>

      <p className="auth-footer">
        Your documents, intelligently indexed.
      </p>
    </div>
  )
}
