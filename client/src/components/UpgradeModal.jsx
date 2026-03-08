import React, { useState } from 'react'
import { X, Check, Crown, FileText, MessageSquare, Zap } from 'lucide-react'
import { createSubscription } from '../api'

const FEATURES = [
  { icon: FileText, text: 'Upload up to 20 documents' },
  { icon: MessageSquare, text: 'Unlimited questions per day' },
  { icon: Zap, text: 'Priority processing' },
]

export default function UpgradeModal({ isOpen, onClose, userEmail, onSuccess }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  if (!isOpen) return null

  const handleUpgrade = async () => {
    setLoading(true)
    setError(null)

    try {
      const { subscription_id, razorpay_key_id } = await createSubscription(userEmail)

      // Open Razorpay Checkout
      const options = {
        key: razorpay_key_id,
        subscription_id: subscription_id,
        name: 'DocAgent',
        description: 'Pro Plan — Monthly Subscription',
        handler: function (response) {
          // Payment successful — webhook will update the plan
          onSuccess?.()
          onClose()
        },
        prefill: {
          email: userEmail,
        },
        theme: {
          color: '#7c6f5e',
        },
        modal: {
          ondismiss: function () {
            setLoading(false)
          },
        },
      }

      const rzp = new window.Razorpay(options)
      rzp.open()
      setLoading(false)
    } catch (err) {
      setError(err.message || 'Failed to start checkout. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div className="upgrade-overlay" onClick={onClose}>
      <div className="upgrade-modal" onClick={e => e.stopPropagation()}>
        <button className="upgrade-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>

        <div className="upgrade-icon">
          <Crown size={32} color="var(--accent)" />
        </div>

        <h2 className="upgrade-title">Upgrade to Pro</h2>
        <p className="upgrade-subtitle">
          Unlock the full power of DocAgent with more documents and unlimited questions.
        </p>

        <div className="upgrade-features">
          {FEATURES.map(({ icon: Icon, text }, i) => (
            <div key={i} className="upgrade-feature">
              <div className="upgrade-feature-check">
                <Check size={14} />
              </div>
              <span>{text}</span>
            </div>
          ))}
        </div>

        {error && <p className="upgrade-error">{error}</p>}

        <button
          className="upgrade-btn"
          onClick={handleUpgrade}
          disabled={loading}
        >
          {loading ? <span className="auth-spinner" /> : 'Subscribe Now'}
        </button>

        <p className="upgrade-note">
          Secure payment via Razorpay. Cancel anytime.
        </p>
      </div>
    </div>
  )
}
