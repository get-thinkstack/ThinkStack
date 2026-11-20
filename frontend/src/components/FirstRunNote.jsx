import { useEffect, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { firstRunNoteSeen, markFirstRunNoteSeen } from '../utils/firstRun';

/**
 * Told once, on a new install: the app runs a language model on this machine,
 * and Bench is where it is chosen. A banner, not a dialog, and it never
 * returns (the dialog it replaced interrupted and kept coming back).

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
        <strong>ThinkStack runs language models on your own machine.</strong>
        <p>
          Nothing is sent anywhere. No model comes with the app: pick one in
          Bench, or use one you already have through Ollama or LM Studio.
          Reading, search and writing LaTeX work without one; summaries, gap
          finding and writing at the cursor need one.
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
