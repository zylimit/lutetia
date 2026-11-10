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
  signoutoffline: 'Signing out needs a connection.', // new: Task 11.1, offline Sign out keeps the session and the saved data
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
  // Bundles (Task 10.1). Trackers only: no copper bundle number, no trip status (Architecture §9, Spec #96).
  bundlesnote: 'Shows last position and 7-day track only; trip status is not computed yet',
  bundlesmap: 'Tracker positions',
  bundlelist: 'Trackers',
  nopos24: 'No GPS tracker has reported in the last 24 h',
  lastpositionat: 'Last position: {t}',
  notrackers: 'No GPS tracker registered yet.',
  trackof: 'Track of {who}, last 7 days',
  tracknone: 'No track points in the last 7 days',
  trackfailed: 'Couldn’t load the track. Select the tracker again to retry.',
  trackstart: 'Track start',
  trackend: 'Track end',
  trackpoints: '{n} points',
  trackpoints1: '{n} point',
  hidetrack: 'Hide track',
  bundlesfailed: 'Couldn’t load the trackers. Retrying in 60 s — or reload now.',
  loadingState: 'Loading',
  // Plan (Task 10.2) and SLA reference (Task 10.3). Excel snapshot; SLA durations parsed at import, never shown in Chinese.
  sourcesnapshot: 'Excel snapshot, as of {t} · Ariane is the source of truth', // {t}: the resource as_of
  sourceariane: 'From Ariane, as of {t}', // new: once /api/v1/pois says source ariane
  filters: 'Filters',
  uci: 'UCI', // new
  sub: 'Subcontractor',
  commune: 'Commune',
  category: 'Category',
  infrastructure: 'Underground / Aerial',
  cable: 'Cable type',
  all: 'All',
  clear: 'Clear filters',
  removefilter: 'Remove filter: {f}', // new
  bysub: 'Planned tonnes by subcontractor',
  bycable: 'Planned tonnes by cable type',
  covers: 'Covers {n} of {m} work orders — only work orders with a planned weight count', // demo key covers, made a template; counts orders with a planned weight (review L-3)
  chartnone: 'No planned weight in these work orders', // new
  cablechartfailed: 'Couldn’t load the cable segments for this chart. Reload to retry.', // new
  notset: 'Not set', // new: empty ledger cell in a chart or filter
  orders: 'Work orders',
  segments: 'Segments',
  length: 'Length (km)',
  planned: 'Planned (t)',
  received: 'Received',
  opdate: 'Planned op date',
  occ: 'OCC', // new
  pending: 'Weight pending',
  ariane: 'Open in Ariane', // demo key ariAne
  exportcsv: 'Export filtered rows (CSV)', // demo key export
  exportfailed: 'Couldn’t build the CSV. Reload and try again.', // new
  nomatch: 'No work order matches these filters.',
  noorders: 'No work order imported yet.', // new
  expand: 'Expand segments',
  collapse: 'Collapse segments',
  nodetail: 'Cable detail pending. Weight is not available.',
  segmentsfailed: 'Couldn’t load the segments. Collapse and expand to retry.', // new
  seq: 'No.', // new
  segmentn: 'Segment {n}', // new
  drawernodata: 'This manhole’s data isn’t loaded, so its state is unknown. Reload to try again.', // new
  cablecategory: 'Cable category', // new
  network: 'Network', // new
  weight: 'Weight (t)',
  planfailed: 'Couldn’t load the work orders. Retrying in 60 s — or reload now.', // new
  sla: 'SLA reference',
  refonly: 'Reference only — not tracked per work order',
  slanone: 'SLA templates not imported yet.', // new
  slafailed: 'Couldn’t load the SLA templates. Reload to retry.', // new
  slamatch: 'Matches the Category filter', // new
  step: 'Step', // new
  owner: 'Responsible', // new
  sladuration: 'SLA', // new
  ownercustomer: 'Customer', // new
  ownerhuawei: 'Huawei', // new
  ownerpartner: 'Partner', // new
  seesource: 'see source table', // new: SLA duration not parsed at import
  tplTransportation: 'Transportation', // demo key transportation
  tplDistribution: 'Distribution',
  tplMASSIVE: 'Massive', // demo key massive
  uminute: '{n} min', // new: SLA units, {n} is a number or a range
  uminute1: '{n} min', // new
  uhour: '{n} h', // new
  uhour1: '{n} h', // new
  uday: '{n} days', // new
  uday1: '{n} day', // new
  uworkday: '{n} working days', // new
  uworkday1: '{n} working day', // new
  uweek: '{n} weeks', // new
  uweek1: '{n} week', // new
  umonth: '{n} months', // new
  umonth1: '{n} month', // new
  utonne_per_day: '{n} t/day', // new: dismantling rate
  utonne_per_day1: '{n} t/day', // new
  ordercount: '{n} work orders', // new
  ordercount1: '{n} work order', // new
  matchingonly: 'matching segments only', // new
  scopeaccess: 'Access layer: {d}', // new
  scopeaggregation: 'Aggregation layer: {d}', // new
  scopebackbone: 'Backbone layer: {d}', // new
  scopeother: '{d} (scope in source table)', // new
  // embedded widgets (Phase 12, CMP-11)
  embedsignin: 'Sign in to Lutetia to see this.', // new
  embedopen: 'Open sign-in', // new
  embedopenhint: 'opens in a new tab', // new: screen readers, the link leaves the host page
}

export type Key = keyof typeof en
