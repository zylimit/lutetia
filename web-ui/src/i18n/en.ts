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
  // Overview and Manholes (Task 9.3). {n} {m} {t} {range} are filled in by tf().
  security: 'Security status',
  moved24: 'Moved in last 24 h',
  offline: 'Offline',
  online: 'Online',
  quiet: 'Quiet',
  moved: 'Moved',
  moving: 'Moving now',
  inactive: 'Inactive', // new: not expected online or never configured (Decisions 2026-11-10)
  suspicious: 'Offline during a movement', // new: offline with an unfinished event (Decisions 2026-11-10)
  movedaria: '{n} manholes moved in last 24 hours', // new
  movedaria1: '{n} manhole moved in last 24 hours', // new
  offlinearia: '{n} manholes offline', // new
  offlinearia1: '{n} manhole offline', // new
  onlinearia: '{n} manholes online and quiet', // new
  onlinearia1: '{n} manhole online and quiet', // new
  manholecount: '{n} manholes', // new
  manholecount1: '{n} manhole', // new
  movingcount: '{n} moving now', // new
  offlineopen: '{n} offline during a movement', // new
  inactivecount: '{n} inactive, not monitored', // new
  inactivecount1: '{n} inactive, not monitored', // new
  latest: 'Latest movement events',
  events: 'Movement events',
  event: 'Movement event',
  location: 'Location unverified',
  notified: 'Notified',
  duration: 'Duration',
  flips: 'Flips',
  ongoing: 'Ongoing',
  min: 'min',
  hour: 'h', // new
  days: 'd',
  allquiet: 'All {n} manholes quiet since {t}',
  allquiet1: 'The manhole has been quiet since {t}', // new
  allquietever: 'All {n} manholes quiet', // new: no movement ever recorded
  allquietever1: 'The manhole is quiet', // new
  emptymanholes: 'No manholes registered yet.', // new
  noevents24: 'No movement in the last 24 hours', // new
  noevents: 'No movement in the last 7 days',
  noevents30: 'No movement in the last 30 days', // new
  noeventsever: 'No movement recorded yet.', // new
  nomovement: 'No movement in this period',
  range: 'Time range',
  map: 'Manhole locations',
  legend: 'Marker legend',
  nolocation: '{n} without a position', // new
  manholelist: 'Manholes in this view', // new: CMP-7, the list equivalent of the map
  viewmap: 'View map', // new
  viewevents: 'View movement events',
  sort: 'Newest first',
  status: 'Status',
  clearfilter: 'Clear filter', // new
  name: 'Name', // new
  lastreport: 'Last report',
  never: 'Never reported',
  voltage: 'Voltage',
  signal: 'Signal (RSRP)',
  period: 'Period',
  close: 'Close',
  chartempty: 'No readings in this period', // new
  charttruncated: 'Showing the newest {n} readings, from {t}', // new
  eventsfailed: 'Couldn’t load the movement events. Close and open again to retry.', // new
  seriesfailed: 'Couldn’t load the readings. Close and open again to retry.', // new
  copper: 'Copper bundles',
  trackercount: '{n} trackers', // new
  trackercount1: '{n} tracker', // new
  trackeronline: '{n} online', // new
  lastposition: 'Last position',
  viewbundles: 'View bundles',
  removal: 'Removal plan',
  workorders: 'work orders',
  workorder1: 'work order', // new
  detailcount: 'with cable detail',
  plannedtotal: '{t} t planned',
  pendingweight: 'Weight pending for {n} of {m}', // demo key pending92, made a template
  openplan: 'Open plan',
  offlinebanner: 'Offline · data as of {t}',
  offlinebannernone: 'Offline · no data loaded yet', // new
  delaybanner: 'Data may be delayed — collector last seen {t}',
  delaybannernever: 'Data may be delayed — collector not seen yet', // new
  errorbanner: 'Couldn’t load events. Retrying in 60 s — or reload now.',
  loadingState: 'Loading',
}

export type Key = keyof typeof en
