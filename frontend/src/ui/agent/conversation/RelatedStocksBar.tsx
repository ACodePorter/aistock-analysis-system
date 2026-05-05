import React from 'react'
import { Tag } from 'antd'
import type { RelatedStock } from '../../../api/agent'

function roleText(role: RelatedStock['role']) {
  if (role === 'current_context') return '当前'
  if (role === 'candidate') return '候选'
  if (role === 'holding') return '持仓'
  return '提及'
}

export default function RelatedStocksBar({ stocks }: Readonly<{ stocks: RelatedStock[] }>) {
  if (!stocks.length) return null
  return (
    <div className="agent-related-stocks">
      {stocks.map(stock => (
        <Tag key={`${stock.role}-${stock.code}`} color={stock.role === 'holding' ? 'orange' : 'blue'}>
          {roleText(stock.role)} {stock.name || stock.code}
        </Tag>
      ))}
    </div>
  )
}
