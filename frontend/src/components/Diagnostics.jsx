import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X, Cpu, HardDrive, Gauge, Lightbulb } from 'lucide-react';
import { systemApi } from '../utils/api';

/**
 * "What can my machine do?"
 *
 * The app profiles the machine once at startup and caches it, which is the
 * right trade: hardware does not change while the app runs, and probing on
 * every launch would slow every launch. The cost is that a user who adds
 * memory, closes a memory-hog, or upgrades from a build that predates this
 * screen has no way to make the app look again. This is that way.
 *
 * Deliberately renders whatever `report()` returns rather than knowing the
 * shape in detail. When this is merged with "Add better models", the picker
 * consumes the same payload -- `limits` decides which models are honest
 * suggestions, and `advice` is already written in the user's language.
 *
 * It shows and never acts: no downloads, no settings changed. Anything that
 * costs bytes belongs behind consent, which is a different screen.
 */
export default function Diagnostics({ open, onClose }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setBusy(true);
    setError('');
    systemApi
      .diagnose()
      .then((r) => !cancelled && setReport(r))
      .catch((e) => !cancelled && setError(e.message || 'could not read this machine'))
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const m = report?.machine;
  const e = report?.engine;
  const l = report?.limits;

  // A GPU that exists but cannot be used is the single most confusing state,
  // so it is named rather than left for the user to infer from two numbers.
  const gpuLine = !m
    ? ''
    : m.gpu_name
      ? `${m.gpu_name}${e?.gpu_offload_supported ? '' : ' (not usable by this build)'}`
      : 'none detected';

  return (
    <AnimatePresence>
      <motion.div
        className="model-setup-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <motion.div
          className="model-setup-card"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 260, damping: 24 }}
        >
          <button className="model-setup-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>

          <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Gauge size={20} /> Your machine
          </h2>

          {busy && <p style={{ color: 'var(--text-secondary)' }}>Examining this machine…</p>}

          {error && (
            <p style={{ color: 'var(--warning)' }}>
              Could not read this machine: {error}
            </p>
          )}

          {report && !busy && (
            <>
              <div style={{ display: 'grid', gap: '0.6rem', margin: '1rem 0' }}>
                <Row icon={<HardDrive size={15} />} label="Memory"
                     value={`${m.available_ram_gb} GB free of ${m.total_ram_gb} GB`} />
                <Row icon={<Cpu size={15} />} label="Processor"
                     value={`${m.cpu_cores} cores · ${m.tier} tier`} />
                <Row icon={<Gauge size={15} />} label="Graphics" value={gpuLine} />
                <Row icon={<Gauge size={15} />} label="Reads at once"
                     value={`about ${Math.round(l.input_chars / 1000)}k characters`} />
              </div>

              {report.advice?.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <h3 style={{
                    fontSize: '0.9rem', display: 'flex', alignItems: 'center',
                    gap: '0.4rem', marginBottom: '0.5rem',
                  }}>
                    <Lightbulb size={15} /> What this means
                  </h3>
                  <ul style={{
                    color: 'var(--text-secondary)', fontSize: '0.88rem',
                    lineHeight: 1.7, paddingLeft: '1.1rem',
                  }}>
                    {report.advice.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}
            </>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

/**
 * The machine, rendered. Shared by the modal above and the Forge page, so the
 * two can never drift into describing the same hardware differently.
 */
export function MachineReport({ report }) {
  const m = report?.machine;
  const e = report?.engine;
  const l = report?.limits;
  if (!m || !l) return null;

  // A GPU that exists but cannot be used is the single most confusing state,
  // so it is named rather than left for the user to infer from two numbers.
  const gpuLine = m.gpu_name
    ? `${m.gpu_name}${e?.gpu_offload_supported ? '' : ' (not usable by this build)'}`
    : 'none detected';

  return (
    <>
      <div style={{ display: 'grid', gap: '0.6rem', margin: '1rem 0' }}>
        <Row icon={<HardDrive size={15} />} label="Memory"
             value={`${m.available_ram_gb} GB free of ${m.total_ram_gb} GB`} />
        <Row icon={<Cpu size={15} />} label="Processor"
             value={`${m.cpu_cores} cores · ${m.tier} tier`} />
        <Row icon={<Gauge size={15} />} label="Graphics" value={gpuLine} />
        <Row icon={<Gauge size={15} />} label="Reads at once"
             value={`about ${Math.round(l.input_chars / 1000)}k characters`} />
      </div>

      {report.advice?.length > 0 && (
        <div style={{ marginTop: '0.5rem' }}>
          <h3 style={{
            fontSize: '0.9rem', display: 'flex', alignItems: 'center',
            gap: '0.4rem', marginBottom: '0.5rem',
          }}>
            <Lightbulb size={15} /> What this means
          </h3>
          <ul style={{
            color: 'var(--text-secondary)', fontSize: '0.88rem',
            lineHeight: 1.7, paddingLeft: '1.1rem',
          }}>
            {report.advice.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}

function Row({ icon, label, value }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.9rem' }}>
      <span style={{ opacity: 0.7, display: 'flex' }}>{icon}</span>
      <span style={{ minWidth: '7.5rem', color: 'var(--text-secondary)' }}>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
