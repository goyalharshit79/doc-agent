import React, { useState, useEffect } from 'react'
import { Eye, EyeOff, MailCheck, ArrowLeft, KeyRound } from 'lucide-react'
import { login, signup, forgotPassword, resetPassword } from '../api'

export default function AuthPage({ onAuth }) {
  const [mode, setMode]               = useState('login')   // 'login' | 'signup' | 'forgot' | 'reset'
  const [email, setEmail]             = useState('')
  const [password, setPassword]       = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError]             = useState(null)
  const [loading, setLoading]         = useState(false)
  const [notice, setNotice]           = useState(null)

  // Check URL for password reset token on mount
  useEffect(() => {
    const hash = window.location.hash
    if (hash) {
      const params = new URLSearchParams(hash.substring(1))
      const accessToken = params.get('access_token')
      const type = params.get('type')
      if (accessToken && type === 'recovery') {
        // Store token and switch to reset mode
        localStorage.setItem('docagent_reset_token', accessToken)
        setMode('reset')
        // Clean up URL
        window.history.replaceState(null, '', window.location.pathname)
      }
    }
  }, [])

  const handleSubmit = async () => {
    setError(null)
    setNotice(null)

    // ── Forgot password ──
    if (mode === 'forgot') {
      if (!email) { setError('Please enter your email.'); return }
      setLoading(true)
      try {
        await forgotPassword(email)
        setNotice('If that email is registered, you\'ll receive a password reset link shortly.')
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
      return
    }

    // ── Reset password ──
    if (mode === 'reset') {
      if (!newPassword) { setError('Please enter a new password.'); return }
      if (newPassword.length < 8) { setError('Password must be at least 8 characters.'); return }
      setLoading(true)
      try {
        const token = localStorage.getItem('docagent_reset_token')
        if (!token) { setError('Reset token missing. Please request a new link.'); setLoading(false); return }
        await resetPassword(token, newPassword)
        localStorage.removeItem('docagent_reset_token')
        setNotice('Password updated! You can now sign in with your new password.')
        setMode('login')
        setNewPassword('')
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
      return
    }

    // ── Login / Signup ──
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
          if (res.refresh_token) {
            localStorage.setItem('docagent_refresh_token', res.refresh_token)
          }
          onAuth({ token: res.access_token, userId: res.user_id, email: res.email })
        }
      } else {
        const res = await login(email, password)
        localStorage.setItem('docagent_token', res.access_token)
        if (res.refresh_token) {
          localStorage.setItem('docagent_refresh_token', res.refresh_token)
        }
        onAuth({ token: res.access_token, userId: res.user_id, email: res.email })
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => { if (e.key === 'Enter') handleSubmit() }

  // ── Tagline text ──
  const taglines = {
    login: 'Welcome back.',
    signup: 'Create your account.',
    forgot: 'Reset your password.',
    reset: 'Set a new password.',
  }

  return (
    <div className="auth-root">
      <div className="auth-grain" />

      <div className="auth-card" style={{ animationDelay: '0.05s' }}>

        {/* Logo */}
        <div className="auth-logo">
          <span className="logo-mark">D</span>
          <span className="logo-text">oc<em>Agent</em></span>
        </div>

        <p className="auth-tagline">{taglines[mode]}</p>

        {/* Mode toggle — only for login/signup */}
        {(mode === 'login' || mode === 'signup') && (
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
        )}

        {/* Back button for forgot/reset */}
        {(mode === 'forgot' || mode === 'reset') && (
          <button
            className="auth-back-btn"
            onClick={() => { setMode('login'); setError(null); setNotice(null) }}
          >
            <ArrowLeft size={14} />
            <span>Back to sign in</span>
          </button>
        )}

        {/* Fields */}
        <div className="auth-fields">
          {/* Email — shown for login, signup, forgot */}
          {mode !== 'reset' && (
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
          )}

          {/* Password — shown for login, signup */}
          {(mode === 'login' || mode === 'signup') && (
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
          )}

          {/* New password — shown for reset */}
          {mode === 'reset' && (
            <div className="auth-field">
              <label className="auth-label">New Password</label>
              <div className="auth-input-wrap">
                <input
                  className="auth-input auth-input--has-toggle"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Min. 8 characters"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  onKeyDown={handleKey}
                  autoFocus
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
          )}
        </div>

        {/* Forgot password link — only on login */}
        {mode === 'login' && (
          <button
            className="auth-forgot-link"
            onClick={() => { setMode('forgot'); setError(null); setNotice(null) }}
          >
            Forgot password?
          </button>
        )}

        {/* Feedback */}
        {error && <p className="auth-error">{error}</p>}
        {notice && (
          <div className="auth-notice auth-notice--prominent">
            <div className="auth-notice-icon">
              {mode === 'reset' || mode === 'login' ? <KeyRound size={20} /> : <MailCheck size={20} />}
            </div>
            <div>
              <p className="auth-notice-title">
                {mode === 'forgot' ? 'Check your email' : mode === 'login' ? 'Password updated' : 'Verification required'}
              </p>
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
            : mode === 'login' ? 'Sign in'
            : mode === 'signup' ? 'Create account'
            : mode === 'forgot' ? 'Send reset link'
            : 'Update password'
          }
        </button>

      </div>

      <p className="auth-footer">
        Your documents, intelligently indexed.
      </p>
    </div>
  )
}
