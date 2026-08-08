/**
 * page header with the app's signature: the title carries an acid-green
 * "brush-slash" underline that draws itself on mount (stroke-dashoffset).
 * ported from the landing page's hero treatment.
 *
 * the slash stretches to the title's width with a non-scaling stroke, so it
 * stays an even hand-drawn line whatever the title length. reduced-motion is
 * respected globally (the draw collapses to an instant reveal).
 *
 * pass action buttons as children - they align to the title baseline on the
 * right, replacing the ad-hoc per-page header markup (and its alignment bugs).
 *
 * There is no subtitle. A sentence explaining the page is worth reading once
 * and was then occupying a strip of every screen forever -- which Scribe needs
 * for its editor and preview to have half the height each. That copy now lives
 * in features.js and is shown by the "i" in the bottom-left corner.
 */
export default function PageHeader({ title, className = '', children }) {
  return (
    <div className={`page-header ${className}`.trim()}>
      <div className="page-header-left">
        <h2 className="ph-title">
          <span className="ph-title-text">{title}</span>
          <svg
            className="ph-slash"
            viewBox="0 0 300 24"
            preserveAspectRatio="none"
            aria-hidden="true"
            focusable="false"
          >
            <path
              className="ph-slash-path"
              d="M2 16 C 70 7, 118 21, 178 12 S 268 8, 298 15"
            />
          </svg>
        </h2>
      </div>
      {children}
    </div>
  );
}
