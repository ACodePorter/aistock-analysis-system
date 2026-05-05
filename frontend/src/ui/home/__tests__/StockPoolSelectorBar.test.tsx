import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StockPoolSelectorBar from '../StockPoolSelectorBar'

const watch = [
  { symbol: '002594.SZ', name: '比亚迪', sector: '新能源', enabled: true, pinned: true },
  { symbol: '300750.SZ', name: '宁德时代', sector: '新能源', enabled: true, pinned: true },
]

function renderBar(overrides = {}) {
  const props = {
    current: '002594.SZ',
    watch,
    name: '',
    searching: false,
    searchResults: [],
    showSearchModal: false,
    professionalMode: false,
    onNameChange: vi.fn(),
    onSearch: vi.fn(),
    onSelectSymbol: vi.fn(),
    onToggleSearchResultPin: vi.fn(),
    onCloseModal: vi.fn(),
    onOpenManager: vi.fn(),
    onModeChange: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  }
  render(<StockPoolSelectorBar {...props} />)
  return props
}

describe('StockPoolSelectorBar', () => {
  it('selects a stock from sticky tags', () => {
    const props = renderBar()

    fireEvent.click(screen.getByRole('button', { name: '宁德时代' }))

    expect(props.onSelectSymbol).toHaveBeenCalledWith('300750.SZ')
  })

  it('runs search when pressing enter', () => {
    const props = renderBar({ name: '比亚迪' })

    fireEvent.keyDown(screen.getByPlaceholderText('搜索代码/名称，回车查看匹配股票'), { key: 'Enter' })

    expect(props.onSearch).toHaveBeenCalled()
  })
})