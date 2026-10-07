import { test, expect } from 'claude-code/testing'

const PANE = {
  component: 'Pane',
  requestId: 'tap-counter',
  props: {
    title: '計數器',
    isFocused: true,
    bodyColumns: 60,
    placement: 'inline',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

test('the pane counts taps and resets on every surface, mobile included', async $ => {
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ plugin: 'tap-counter', surface, ...PANE })
    expect((await ui.find({ type: 'Text', text: /你按了/ }))?.text).toMatch(/0 下/)
    await ui.press({ key: 'tap' })
    await ui.press({ key: 'tap' })
    expect((await ui.find({ type: 'Text', text: /你按了/ }))?.text).toMatch(/2 下/)
    await ui.press({ key: 'reset' })
    expect((await ui.find({ type: 'Text', text: /你按了/ }))?.text).toMatch(/0 下/)
    await ui.unmount()
  }
})
