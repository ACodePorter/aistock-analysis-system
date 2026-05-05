import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import HelpTooltip, { HelpIcon } from '../HelpTooltip'

describe('HelpTooltip', () => {
  it('renders the wrapped control without changing layout semantics', () => {
    render(
      <HelpTooltip title="说明" content="这是一段普通用户能理解的解释。">
        <button type="button">查看说明</button>
      </HelpTooltip>,
    )

    expect(screen.getByRole('button', { name: '查看说明' })).toBeInTheDocument()
  })

  it('renders the default help icon as an accessible hint', () => {
    render(<HelpIcon />)

    expect(screen.getByRole('img', { name: '查看说明' })).toBeInTheDocument()
  })

  it('does not render an empty tooltip wrapper when content is blank', () => {
    render(
      <HelpTooltip content="">
        <button type="button">空提示按钮</button>
      </HelpTooltip>,
    )

    expect(screen.getByRole('button', { name: '空提示按钮' })).toBeInTheDocument()
  })
})