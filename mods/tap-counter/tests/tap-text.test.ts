import { test, expect } from 'claude-code/testing'

const tap = (args: string) =>
  ({ command: 'tap', args, origin: { kind: 'bridge' }, presentation: { isFullscreen: false, columns: 80 } }) as const

test('/tap counts in plain text with no surface attached', async $ => {
  expect((await $.command.run(tap(''))).text).toMatch(/計數器：1/)
  expect((await $.command.run(tap('5'))).text).toMatch(/計數器：6/)
  expect((await $.command.run(tap('4'))).text).toMatch(/計數器：10  🎉/)
  expect((await $.command.run(tap('歸零'))).text).toMatch(/計數器：0/)
})
