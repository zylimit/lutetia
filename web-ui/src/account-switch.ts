// Pure rule for "another account signed in on this device" (Task 11.1 L1), unit-tested in account-switch.test.ts.
export const ACCOUNT_KEY = 'lutetia.account' // localStorage: the account name only, never data

/** The saved API answers must go when the account differs from the last one, or when the last one is unknown
 * (first use, storage cleared or blocked): an unknown previous account may be someone else. */
export function mustClearForAccount(previous: string | null, current: string): boolean {
  return previous !== current
}
