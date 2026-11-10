// risk: low
import { describe, expect, it } from 'vitest'
import { pickLang } from './pick'

describe('pickLang', () => {
  it('takes the first English or French entry of the preference list', () => {
    expect(pickLang(null, ['de', 'fr'])).toBe('fr')
    expect(pickLang(null, ['fr-CA', 'en'])).toBe('fr')
    expect(pickLang(null, ['en-GB', 'fr'])).toBe('en')
  })
  it('falls back to en when none of them is English or French', () => {
    expect(pickLang(null, ['de'])).toBe('en')
    expect(pickLang(null, [])).toBe('en')
    expect(pickLang(null, undefined)).toBe('en')
  })
  it('still takes a single tag, and a stored choice wins', () => {
    expect(pickLang(null, 'fr-FR')).toBe('fr')
    expect(pickLang('en', ['fr'])).toBe('en')
    expect(pickLang('xx', ['fr'])).toBe('fr')
  })
})
