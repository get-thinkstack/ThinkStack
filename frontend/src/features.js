/**
 * Every feature in the application, declared once.
 *
 * The shell used to describe each feature in three separate places -- a nav
 * entry, a <Route>, and (for the logo) nothing at all, because the mark was
 * hardcoded SVG pasted in twice. Adding a feature meant remembering all of
 * them, and the two copies of the logo could and did drift apart.
 *
 * This array is the single source. The nav, the routes and the brand mark are
 * all rendered FROM it, so adding a feature is one entry and the shell needs no
 * edit at all. Nothing here knows what a sidebar is; it is data, which is why
 * it survives a redesign of the shell that reads it.
 *
 * Fields:
 *   id        stable key, independent of the URL, safe for persisted state or
 *             analytics (the path may change; this should not)
 *   path      the route
 *   end       exact-match routing; only "/" needs it, since every other path
 *             would otherwise match it as a prefix
 *   label     what the user reads in the nav
 *   icon      the nav glyph
 *   mark      the brand glyph while this feature is open. Defaults to `icon`,
 *             so a new feature gets a changing logo for free without declaring
 *             anything extra.
 *   Component the page itself, lazily loaded
 */

import { lazy } from 'react';
import { BookOpen, Waypoints, PenLine, Gauge } from 'lucide-react';
import { StackMark } from './components/marks';

// One page is on screen at a time, so one page is worth downloading at a time.
// Loading all four eagerly meant Recharts and the whole canvas engine landed
// before the first paint of whichever page you actually opened.
const Library = lazy(() => import('./components/Library'));
const LitGraph = lazy(() => import('./components/LitGraph'));
const Scribe = lazy(() => import('./components/Scribe'));
const Bench = lazy(() => import('./components/Bench'));

// three sections, in the order the work actually happens:
// collect -> understand -> write. Bench is the workshop behind all of them.
export const FEATURES = [
  {
    id: 'library',
    path: '/',
    end: true,
    label: 'Library',
    icon: BookOpen,
    // Home keeps the house mark: it is the first thing drawn on launch, and
    // that is the moment the product should say its own name. Change this to
    // BookOpen if you would rather every section be equally signposted.
    mark: StackMark,
    Component: Library,
  },
  { id: 'litgraph', path: '/litgraph', label: 'LitGraph', icon: Waypoints, Component: LitGraph },
  { id: 'write', path: '/write', label: 'Scribe', icon: PenLine, Component: Scribe },
  { id: 'bench', path: '/bench', label: 'Bench', icon: Gauge, Component: Bench },
];

/** the glyph to show as the brand mark for a feature (falls back to its icon). */
export const markFor = (feature) => feature?.mark || feature?.icon || StackMark;

/**
 * Which feature owns a URL.
 *
 * Longest matching prefix rather than equality, so a nested route added later
 * -- /write/<project>/<file> when Scribe grows a file tree -- still resolves to
 * Scribe and keeps its mark, instead of silently falling back to the default.
 * "/" is excluded from prefix matching because it prefixes everything.
 */
export function featureForPath(pathname) {
  const exact = FEATURES.find((f) => f.path === pathname);
  if (exact) return exact;

  return FEATURES
    .filter((f) => f.path !== '/' && pathname.startsWith(`${f.path}/`))
    .sort((a, b) => b.path.length - a.path.length)[0] || null;
}
