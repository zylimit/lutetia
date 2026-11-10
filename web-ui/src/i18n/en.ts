// English strings. Keys are the keys of the design prototype's `T` dictionary (demo/index.html); keys marked "new" are not in it.
// Task 9.3 / 10.x add their own keys here and in fr.ts; fr.ts is typed against this object, so a missing French string fails the build.
export const en = {
  // navigation and shell
  overview: 'Overview',
  manholes: 'Manholes',
  bundles: 'Bundles',
  plan: 'Plan',
  asof: 'As of',
  account: 'Account',
  theme: 'Theme',
  dark: 'Dark',
  light: 'Light',
  projection: 'Projection',
  language: 'Language',
  signout: 'Sign out',
  mainnav: 'Main navigation', // new (the prototype hard-codes it)
  comingsoon: 'Coming in a later release', // new
  comingsoonhint: 'This page is not available yet.', // new
  sessionerror: 'Couldn’t check your session. Reload to try again.', // new
  reload: 'Reload now',
  // sign-in
  signin: 'Sign in',
  username: 'Username',
  password: 'Password',
  keep: 'Keep me signed in for 30 days',
  wrong: 'Wrong username or password.',
  locked: 'Too many attempts. Try again in 5 minutes.',
  offlinesignin: 'You’re offline. Sign in needs a connection.',
  signednote: 'Read-only security and project dashboard',
}

export type Key = keyof typeof en
