import { useEffect, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { firstRunNoteSeen, markFirstRunNoteSeen } from '../utils/firstRun';

/**
 * Told once, on a new install: a model is included, and it is yours to change.
 *
 * NOT the modal this replaced. That one interrupted to sell a download, kept
 * its own record of what had been declined, and reappeared after the thing it
 * was offering had been dealt with elsewhere. This states a fact, offers a
 * door, and never comes back.
 *
 * It teaches rather than asks. A researcher has no reason to know that the app
 * runs a language model on their own machine, that it can be swapped, or that
 * the choice affects how good their gap analysis is -- and they will never
 * discover any of it from a screen they have not been told to visit.
 *
 * A banner, not a dialog: nothing is blocked, and dismissing it costs nothing
 * because the same information lives permanently in Bench.
 */


export default function FirstRunNote({ onOpenBench }) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!firstRunNoteSeen()) setShow(true);
  }, []);

  const dismiss = () => {
    markFirstRunNoteSeen();
    setShow(false);
  };

  if (!show) return null;

  return (
    <div className="first-run-note" role="status">
      <span className="first-run-icon"><Sparkles size={16} /></span>

      <div className="first-run-body">
        <strong>ThinkStack includes a small model, so it works right away.</strong>
        <p>
          Everything runs on your own machine — nothing is sent anywhere. The
          included model is good at finding research gaps and drafting LaTeX.
          For better summaries you can add a larger one, or use a model you
          already have. You can also remove the included one entirely.
        </p>
      </div>

      <div className="first-run-actions">
        <button
          className="btn btn-primary btn-sm"
          onClick={() => { markFirstRunNoteSeen(); setShow(false); onOpenBench?.(); }}
        >
          <span>Show me</span>
        </button>
        <button className="btn btn-ghost btn-sm" onClick={dismiss} aria-label="Dismiss">
          <X size={15} />
        </button>
      </div>
    </div>
  );
}
