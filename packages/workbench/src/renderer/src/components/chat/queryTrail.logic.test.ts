import { expect, it } from 'vitest'
import { annotationContextNote } from '../../lib/browser-annotation'
import { queryDisplayText } from './queryTrail.logic'

it('hides the browser screenshot context note from the query trail', () => {
  const note = annotationContextNote('.deepseek/pasted/shot.png', true, 'https://www.baidu.com/')
  expect(queryDisplayText(`@.deepseek/pasted/shot.png\n圈出来的是什么？\n${note}`)).toBe('@.deepseek/pasted/shot.png 圈出来的是什么？')
})
