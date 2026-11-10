// Pure rule for "another account signed in on this device" (Task 11.1 L1), unit-tested in account-switch.test.ts.
export const ACCOUNT_KEY = 'lutetia.account' // localStorage: the account name only, never data

/** The saved API answers must go when the account differs from the last one, or when the last one is unknown
 * (first use, storage cleared or blocked): an unknown previous account may be someone else. With storage unusable the last
 * account is never known, so `clearedFor` (this page session's memory of the account it already cleared for) stops the clearing
 * from repeating on every navigation, which would switch the offline copy off. */
export function mustClearForAccount(previous: string | null, current: string, clearedFor: string | null = null): boolean {
  if (previous === null && clearedFor === current) return false
  return previous !== current
}
