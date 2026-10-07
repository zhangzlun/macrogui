import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

const PANE = 'tap-counter'
const taps = atom({ plugin: 'tap-counter', key: 'taps' } as const, 0)
const toolCalls = atom({ plugin: 'tap-counter', key: 'toolCalls' } as const, 0)

export const register: Register = on => {
  const asked = new Set<string>()

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'tap',
      description: '計數器：/tap 加一、/tap 5、/tap 歸零、/tap panel',
    })
    $.ui.toast('tap-counter 已載入，輸入 /tap 打開面板')

    return next(e)
  })

  on('command.run', { command: 'tap' }, async ($, e) => {
    const arg = e.args.trim()
    let count = await read($, taps)

    if (arg === '' || arg === '+1' || /^\d+$/.test(arg)) {
      const step = /^\d+$/.test(arg) ? Number(arg) : 1
      count = await update($, taps, n => n + step)
    } else if (arg === '歸零' || arg === 'reset') {
      count = await update($, taps, () => 0)
    } else if (arg === 'panel') {
      await $.ui.open({ id: PANE, title: '計數器' })
      const surfaces = await $.session.surfaces()

      return {
        text: [
          '已要求打開面板。',
          `連上的介面：${surfaces.join('、') || '無'}`,
          `來要過畫面的：${[...asked].join('、') || '還沒有'}`,
        ].join('\n'),
      }
    }

    const calls = await read($, toolCalls)
    const bar = '█'.repeat(Math.min(count, 20)) + (count > 20 ? '…' : '')
    const cheer = count > 0 && count % 10 === 0 ? '  🎉 整數十！' : ''

    return {
      text: [
        `計數器：${count}${cheer}`,
        bar,
        `這個 session 我呼叫了 ${calls} 次工具`,
        '用法：/tap 加一、/tap 5 加五、/tap 歸零、/tap panel 打開面板',
      ].join('\n'),
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    asked.add(`${e.surface}:提示列`)
    const { Box, Text, Button } = $.ui.resolve(e)
    const count = await read($, taps)

    return (
      <Box>
        <Text>計數器 {count} </Text>
        <Button key="band-tap" label="+1" onPress={() => update($, taps, n => n + 1)} />
      </Box>
    )
  })

  on('tool.call', async ($, e, next) => {
    const n = await update($, toolCalls, count => count + 1)
    $.ui.status(`工具呼叫 ${n} 次`)

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    asked.add(`${e.surface}:面板`)
    const { Box, Text, Button } = $.ui.resolve(e)
    const count = await read($, taps)
    const calls = await read($, toolCalls)

    const press = async () => {
      const next = await update($, taps, n => n + 1)
      if (next % 10 === 0) {
        $.ui.toast(`已經按了 ${next} 下！`)
      }
    }

    return (
      <Box flexDirection="column">
        <Text bold>你按了 {count} 下</Text>
        <Text dimColor>這個 session 的工具呼叫：{calls} 次</Text>
        <Box>
          <Button key="tap" label="+1" onPress={press} />
          <Button key="reset" label="歸零" onPress={() => update($, taps, () => 0)} />
        </Box>
      </Box>
    )
  })
}
