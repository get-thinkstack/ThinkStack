/**
 * Graphics acceleration: what this machine could use, and the offer to use it.
 *
 * The bug this replaces was not a wrong number. A tester's RTX 4050 was
 * detected correctly and reported correctly as unusable by the processor-only
 * engine ThinkStack ships -- and then nothing. A dead end, phrased in terms of
 * an internal component ("the installed inference engine is a CPU-only build"),
 * which reads as a defect rather than as the deliberate trade it is.
 *
 * So this panel does three things the old message did not:
 *
 *   names the device that would actually be used -- a laptop can report three,
 *   and "a GPU" is not actionable when one of them is the processor pretending;
 *
 *   quotes a size that was MEASURED, from the release manifest, because the
 *   figure shown before asking for consent is the figure the user agrees to;
 *
 *   says what happens if it does not work, before it is tried.
 *
 * Every device is listed, including the ones that cannot be used, because a
 * user who can see three in their system settings and one here would reasonably
 * conclude detection is broken.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Cpu, Download, Loader2, X } from 'lucide-react';
import { systemApi } from '../utils/api';

/** bytes the user is being asked to accept, in a unit they read without counting. */
const mb = (n) => `${Math.round((n || 0) / 1048576)} MB`;

export default function Acceleration() {
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const poll = useRef(null);

  const load = useCallback(async () => {
    try {
      setState(await systemApi.acceleration());
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll only while something is running. An idle Bench should not be making a
  // request a second for a progress bar that is not on screen.
  const running = state?.install?.status
    && ['downloading', 'verifying', 'installing'].includes(state.install.status);

  useEffect(() => {
    if (!running) return undefined;
    poll.current = setInterval(load, 700);
    return () => clearInterval(poll.current);
  }, [running, load]);

  if (!state) return null;

  const { plan, devices, install, last_attempt: last } = state;

  // Hardware-driven: a machine with nothing to offer is shown nothing. An
  // explanation of an absent option is still an option taking up the screen,
  // and on a machine with no usable device it is an explanation of something
  // the user cannot act on. The one exception is a failed attempt -- that
  // needs saying, because they asked for it and it did not happen.
  const nothingToOffer = !state.active && !plan?.supported
    && !install && !(last && !last.verified);
  if (nothingToOffer) return null;
  const done = install?.status === 'done';
  const failed = install?.status === 'error';

  const enable = async () => {
    setBusy(true);
    setError('');
    try {
      await systemApi.enableAcceleration();
      await load();
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  const disable = async () => {
    setBusy(true);
    try {
      await systemApi.disableAcceleration();
      await load();
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  return (
    <div className="accel">
      <div className="accel-head">
        <span className="card-title">Graphics acceleration</span>
        {state.active && <span className="accel-badge is-on">On</span>}
      </div>

      {/* Every device, including the unusable ones. A machine reporting three
          and a panel showing one reads as broken detection. */}
      {devices?.devices?.length > 0 && (
        <ul className="accel-devices">
          {devices.devices.map((d) => (
            <li key={d.name} className={d.usable ? '' : 'is-unusable'}>
              <span className="accel-dot" />
              <span className="accel-name">{d.name}</span>
              <span className="accel-kind">
                {d.kind === 'software' ? 'software rendering' : d.kind}
              </span>
              {d.name === devices.would_use && (
                <span className="accel-would">would be used</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* ── already on ── */}
      {state.active && (
        <>
          <p className="accel-note">
            Analysis and drafting are running on your graphics hardware.
          </p>
          <button className="btn btn-secondary btn-sm" onClick={disable} disabled={busy}>
            <Cpu size={14} /><span>Go back to the processor</span>
          </button>
        </>
      )}

      {/* ── in progress ── */}
      {!state.active && running && (
        <div className="accel-progress">
          <div className="accel-bar">
            <div className="accel-fill" style={{ width: `${install.percent}%` }} />
          </div>
          <div className="accel-progress-row">
            <span>
              <Loader2 size={13} className="spin" />{' '}
              {install.status === 'downloading'
                ? `Downloading ${install.downloaded_mb} of ${install.total_mb} MB`
                : install.detail || install.status}
            </span>
            <button className="btn btn-secondary btn-sm"
                    onClick={() => systemApi.cancelAcceleration().then(load)}>
              <X size={13} /><span>Cancel</span>
            </button>
          </div>
        </div>
      )}

      {/* ── finished, needs a restart: the override is read at startup ── */}
      {!state.active && done && (
        <p className="accel-note is-good">
          {install.detail || 'Graphics acceleration is on. Restart ThinkStack to use it.'}
        </p>
      )}

      {/* ── it downloaded and could not run here ── */}
      {!state.active && failed && (
        <p className="accel-note is-warn">{install.error}</p>
      )}

      {/* ── the offer ── */}
      {!state.active && !running && !done && plan?.supported && (
        <>
          <p className="accel-note">
            <b>{plan.device}</b> can run the model{' '}
            {plan.device_kind === 'discrete' ? 'several times' : 'noticeably'} faster
            than your processor.
          </p>
          <p className="accel-fine">
            ThinkStack ships without graphics support to keep the installer small.
            This downloads <b>{plan.measured ? mb(plan.download_bytes) : `about ${plan.download_mb} MB`}</b>{' '}
            — our own graphics engine. Your graphics driver is already installed
            and is not downloaded. It is checked before being switched on, and if
            it cannot run here nothing changes.
          </p>
          {last && !last.verified && last.detail && (
            <p className="accel-note is-warn">
              A previous attempt did not work: {last.detail}
            </p>
          )}
          <button className="btn btn-primary btn-sm" onClick={enable} disabled={busy}>
            {busy ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
            <span>Use {plan.device_kind === 'discrete' ? 'my graphics card' : 'my graphics chip'}</span>
          </button>
        </>
      )}

      {/* Only reached when a previous attempt failed or one is in flight --
          the "nothing to offer" case returned null above. */}
      {!state.active && !running && !plan?.supported && plan?.reason && (
        <p className="accel-note">{plan.reason}</p>
      )}

      {error && <p className="accel-note is-warn">{error}</p>}
    </div>
  );
}
