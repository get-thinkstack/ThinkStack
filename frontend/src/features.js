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
 *   fills     true when the page IS a workspace and should take the whole
 *             window. A reading page keeps a measure because a line of prose
 *             1900px wide is unreadable; a canvas or an editor gets narrower
 *             for no reason at all. Declared here rather than in CSS so a page
 *             carries its own layout intent through a redesign of the shell.
 *   guide     lines shown by the "i" in the bottom-left corner. This replaced
 *             the sentence that used to sit under every page title: worth
 *             reading once, not worth the vertical strip forever. Each line is
 *             `[term, explanation]`; the term is emphasised.
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
    summary: 'Every paper you have ingested, and what ThinkStack has read from it.',
    guide: [
      ['upload', 'drop PDFs in, or use the picker. Ingestion parses, chunks and embeds each one'],
      ['click a paper', 'expand it to see its metadata, chunk count and analysis'],
      ['the lock', 'encrypt a paper at rest with a password (Argon2id + AES-256-GCM)'],
      ['offline', 'nothing here is uploaded anywhere. Embeddings are computed on this machine'],
    ],
    Component: Library,
  },
  {
    id: 'litgraph',
    path: '/litgraph',
    label: 'LitGraph',
    icon: Waypoints,
    summary: 'Your papers as a map, placed by meaning and marked with the gaps between them.',
    fills: true,
    guide: [
      ['drag', 'pan the map'],
      ['shift-drag', 'lasso a region to act on it'],
      ['click a paper', 'open it and frame its neighbours'],
      ['wheel', 'zoom in and out'],
      ['the map is the selector', 'lasso papers, then run summarize, claims, themes or gap-finding on exactly those'],
      ['position means something', 'papers sit near the ones they argue with. Territory is a theme; a marker is a gap'],
    ],
    Component: LitGraph,
  },
  {
    id: 'write',
    path: '/write',
    label: 'Scribe',
    icon: PenLine,
    summary: 'Draft, generate and compile LaTeX papers, entirely offline.',
    fills: true,
    guide: [
      ['the file tree', 'a project is a folder. Drop figures in beside main.tex and \\includegraphics finds them'],
      ['select and Ctrl+Enter', 'turn plain English into LaTeX at your cursor'],
      ['ground it', 'pick papers from your library and the model writes from what they actually say'],
      ['compiling is local', 'the TeX engine ships with the app. No account, no queue, no time limit'],
      ['broken LaTeX still builds', 'missing packages are added for you, and one bad figure will not cost you the PDF'],
    ],
    Component: Scribe,
  },
  {
    id: 'bench',
    path: '/bench',
    label: 'Bench',
    icon: Gauge,
    summary: 'What this machine can run, and what it runs it with.',
    guide: [
      ['your machine', 'measured, not guessed: usable memory, CPU, and whether a GPU can actually be used'],
      ['tasks', 'assign a model per job. Gap finding and Scribe can use a different model from summarizing'],
      ['add a model', 'import a GGUF already on disk, or download one sized for this machine'],
      ['suggestions fit your hardware', 'nothing is offered that this machine cannot load'],
    ],
    Component: Bench,
  },
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
