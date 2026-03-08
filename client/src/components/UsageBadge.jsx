import React from 'react'
import { Zap, Crown } from 'lucide-react'

export default function UsageBadge({ usage, onUpgradeClick }) {
  if (!usage) return null

  const { plan, is_unlimited, documents_used, documents_limit, queries_used, queries_limit } = usage

  // Unlimited users or Pro users get a compact badge
  if (is_unlimited) {
    return (
      <div className="usage-badge usage-badge--unlimited" title="Unlimited access">
        <Crown size={12} />
        <span>Unlimited</span>
      </div>
    )
  }

  if (plan === 'pro') {
    return (
      <div className="usage-badge usage-badge--pro" title="Pro plan">
        <Crown size={12} />
        <span>Pro</span>
        <span className="usage-badge-detail">{documents_used}/{documents_limit} docs</span>
      </div>
    )
  }

  // Free users see full usage info
  const docsNearLimit = documents_used >= documents_limit
  const queriesNearLimit = queries_limit && queries_used >= queries_limit * 0.8

  return (
    <button
      className={`usage-badge usage-badge--free${docsNearLimit || queriesNearLimit ? ' usage-badge--warning' : ''}`}
      onClick={onUpgradeClick}
      title="Click to upgrade"
    >
      <Zap size={12} />
      <span>Free</span>
      <span className="usage-badge-separator">·</span>
      <span className={`usage-badge-detail${docsNearLimit ? ' usage-badge-detail--limit' : ''}`}>
        {documents_used}/{documents_limit} doc{documents_limit !== 1 ? 's' : ''}
      </span>
      <span className="usage-badge-separator">·</span>
      <span className={`usage-badge-detail${queriesNearLimit ? ' usage-badge-detail--limit' : ''}`}>
        {queries_used}/{queries_limit} questions
      </span>
    </button>
  )
}
