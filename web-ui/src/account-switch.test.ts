// risk: medium
import { describe, expect, it } from 'vitest'
import { mustClearForAccount } from './account-switch'

describe('mustClearForAccount', () => {
  it('same account as last time keeps the saved answers', () => {
    expect(mustClearForAccount('orange', 'orange')).toBe(false)
  })
  it('another account clears them', () => {
    expect(mustClearForAccount('orange', 'huawei')).toBe(true)
  })
  it('unknown previous account (first use, storage blocked) clears them', () => {
    expect(mustClearForAccount(null, 'orange')).toBe(true)
  })
  it('storage unusable: cleared once this page session, not again on the next navigation', () => {
    expect(mustClearForAccount(null, 'orange', 'orange')).toBe(false)
  })
  it('already cleared for another account this session: the new account clears again', () => {
    expect(mustClearForAccount(null, 'huawei', 'orange')).toBe(true)
  })
  it('a known different previous account still clears even after an earlier clear', () => {
    expect(mustClearForAccount('orange', 'huawei', 'huawei')).toBe(true)
  })
})
