/**
 * Brand marks.
 *
 * Its own file because `features.js` exports data and helpers, and a module
 * that mixes components with non-components breaks Vite's fast refresh -- the
 * whole module reloads instead of the component, so editing the registry would
 * drop the app's state on every keystroke.
 *
 * Every mark here matches lucide's icon API (a `size` prop, `currentColor`
 * stroke) so the registry can hold ours and theirs interchangeably and never
 * has to know which is which.
 */

/**
 * The ThinkStack mark: three stacked layers.
 *
 * Previously written out twice as inline SVG in App.jsx -- once in the sidebar
 * brand and once in the collapsed peek button. Two copies of a logo is one copy
 * too many; they were already free to drift.
 */
export function StackMark({ size = 24, ...rest }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2.5"
      strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" {...rest}
    >
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  );
}
