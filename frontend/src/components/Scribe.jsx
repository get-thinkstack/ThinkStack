import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Save, Play, Download, Sparkles, FileText, Loader2, BookOpen, ChevronDown,
} from 'lucide-react';
import { papersApi, documentsApi, projectFilesApi, useLlmBusy } from '../utils/api';
import PageHeader from './PageHeader';
import FileTree from './FileTree';
import { isImage, isPdf } from '../utils/filekind';
import useSplitter from '../utils/useSplitter';

const AUTOCOMPILE_KEY = 'thinkstack.paperWriter.autoCompile';

// Narrower than this and the editor stops being one: LaTeX is long lines, and a
// column that wraps \begin{figure}[htbp] three times is not somewhere anyone
// writes a paper. Every divider on the page is limited by this and not by a
// fraction of the window.
const EDITOR_MIN_W = 340;

/**
 * Insert generated LaTeX where the author is working.
 *
 * Previously this always went just before \end{document}, so asking for a
 * section put it at the bottom of the paper no matter where the cursor was,
 * and the author then had to cut and paste it into place. Writing at the caret
 * is what makes this feel like editing a document rather than appending to one.
 *
 * The caret is nudged out of the preamble and out of the trailing
 * \end{document}, because neither is a legal place for body content.
 */
function insertLatexAt(src, gen, caret) {
  if (!gen) return { text: src, caretAfter: caret };

  const bodyStart = (() => {
    const m = src.indexOf('\\begin{document}');
    return m === -1 ? 0 : m + '\\begin{document}'.length;
  })();
  const bodyEnd = (() => {
    const m = src.lastIndexOf('\\end{document}');
    return m === -1 ? src.length : m;
  })();

  let at = typeof caret === 'number' ? caret : bodyEnd;
  if (at < bodyStart) at = bodyStart;   // caret was in the preamble
  if (at > bodyEnd) at = bodyEnd;       // caret was past \end{document}

  // keep the insertion on its own lines so the source stays readable
  const before = src.slice(0, at).replace(/\s+$/, '');
  const after = src.slice(at).replace(/^\s+/, '');
  const text = `${before}\n\n${gen}\n\n${after}`;
  return { text, caretAfter: before.length + 2 + gen.length };
}

/**
 * AI LaTeX paper writer.
 *
 * The compiled PDF is the only preview, and it recompiles on its own a moment
 * after you stop typing -- you write, you watch the paper update, you save when
 * you are done. There used to be a second "live preview" that re-rendered the
 * source with KaTeX in the browser; it was removed because it was a second,
 * worse renderer that disagreed with the real PDF, so the thing you were
 * looking at was never the thing you would publish.
 *
 * Compiling writes the source first, so an autocompile is also an autosave.
 * Save stays as an explicit checkpoint.
 */
export default function Scribe() {
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [source, setSource] = useState('');
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [autoStatus, setAutoStatus] = useState(''); // '', 'compiling', 'ok', 'error'
  // source of the last successful compile, so idling does not recompile an
  // unchanged document over and over on a slow CPU.
  const compiledSrc = useRef(null);
  const compileTimer = useRef(null);
  const inFlight = useRef(false);
  // bumped on every successful compile so the iframe src changes and reloads.
  // a counter, not Date.now(): the value only has to differ, and calling an
  // impure clock in a render path is exactly what the react purity rule warns
  // about.
  const pdfVersion = useRef(0);
  const editorRef = useRef(null);
  // one-step undo for an AI edit. The textarea's own undo stack does not
  // survive a programmatic value change, so replacing a selection would
  // otherwise be unrecoverable -- and the model is not always right.
  const [undoSrc, setUndoSrc] = useState(null);

  // Which file the editor is showing. A project is a directory now, so "the
  // source" is no longer synonymous with main.tex -- but main.tex is still the
  // document the compiler builds, so opening a section file changes what you
  // are editing and not what gets compiled.
  const [openFile, setOpenFile] = useState('main.tex');
  // Set when the open file is a figure rather than text: images get a preview
  // where the editor would be, so you can confirm you uploaded the right chart
  // before referencing it.
  const [imagePath, setImagePath] = useState(null);

  // Draggable dividers. Both write a CSS variable straight onto the grid, so a
  // drag costs no re-render, and both remember where you left them -- someone
  // who widens the PDF to read it wants it wide tomorrow too.
  //
  // Both dividers move columns of the SAME three-column grid, so they share one
  // ref, and neither may squeeze the middle column -- the editor -- below the
  // width at which LaTeX stops being writable. Neither divider has a percentage
  // ceiling: a grip that stops partway across with room still visible reads as
  // broken rather than considered, which is exactly what LitGraph's panel got
  // wrong at 50%. The limit is a real one instead, stated in the pixels the
  // other two columns need.
  const gridRef = useRef(null);
  const gridPx = (name, fallback) =>
    parseInt(gridRef.current?.style.getPropertyValue(name), 10) || fallback;

  // Stable identities: `reserve` is a dependency of the hook's clamp, so a new
  // function every render would re-run the effect that applies the stored width
  // and snap a pane back mid-interaction.
  const keepForTree = useCallback(() => gridPx('--pv-w', 520) + EDITOR_MIN_W, []);
  const keepForPreview = useCallback(() => gridPx('--ft-w', 200) + EDITOR_MIN_W, []);

  const {
    onPointerDown: onTreeGrip,
    onKeyDown: onTreeGripKey,
  } = useSplitter({
    varName: '--ft-w', storageKey: 'ts.scribe.treeW',
    // a file list does not get more useful past a point; the editor and the
    // preview do, so the tree is the one pane with a ceiling of its own
    initial: 200, min: 140, max: 420, reserve: keepForTree,
    ref: gridRef,
  });
  const {
    onPointerDown: onPreviewGrip,
    onKeyDown: onPreviewGripKey,
  } = useSplitter({
    varName: '--pv-w', storageKey: 'ts.scribe.previewW',
    initial: 520, min: 260, reserve: keepForPreview,
    fromRight: true,
    ref: gridRef,
  });

  // Autocompile is on by default -- watching the paper build itself is the
  // point. It is a preference, not a policy: a real TeX run costs CPU, and on
  // a slow machine or a large document someone may well want to drive it by
  // hand. Remembered so the choice survives a restart.
  const [autoCompile, setAutoCompile] = useState(() => {
    try {
      return localStorage.getItem(AUTOCOMPILE_KEY) !== 'off';
    } catch {
      return true;
    }
  });

  const toggleAutoCompile = () =>
    setAutoCompile((on) => {
      try {
        localStorage.setItem(AUTOCOMPILE_KEY, on ? 'off' : 'on');
      } catch {
        /* private mode: the preference just will not persist */
      }
      return !on;
    });

  // single shared local model - block AI generate while it's busy elsewhere
  const { busy: llmBusy, label } = useLlmBusy();

  // grounding: which uploaded papers the AI should use as context
  const [docs, setDocs] = useState([]);
  const [groundDocs, setGroundDocs] = useState([]);
  const [showContext, setShowContext] = useState(false);

  const flash = (msg) => {
    setStatus(msg);
    setTimeout(() => setStatus(''), 2500);
  };

  const loadProjects = useCallback(async () => {
    try {
      const d = await papersApi.list();
      setProjects(d.projects || []);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    // fire-and-forget; setState happens in the promise callback, not
    // synchronously inside the effect body
    loadProjects().catch(() => {});
  }, [loadProjects]);

  useEffect(() => {
    documentsApi.list().then((d) => setDocs(d.documents || [])).catch(() => {});
  }, []);

  const toggleGround = (id) =>
    setGroundDocs((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const openProject = async (id) => {
    setError('');
    setStatus('');
    setWarnings([]);
    setPdfUrl(null);
    try {
      const d = await papersApi.get(id);
      setActiveId(id);
      setOpenFile('main.tex');
      setImagePath(null);
      setSource(d.source || '');
      setDirty(false);
      // treat the stored source as already compiled: opening a paper should
      // not immediately re-run TeX on something that has not changed.
      compiledSrc.current = d.source || '';
      setAutoStatus('');
      const proj = projects.find((p) => p.project_id === id);
      if (proj?.has_pdf) {
        pdfVersion.current += 1;
        setPdfUrl(`${papersApi.previewUrl(id)}?v=${pdfVersion.current}`);
      }
    } catch (e) {
      setError(e.message);
    }
  };

  /**
   * Open a file from the tree.
   *
   * One file at a time, as in Overleaf: this replaces what the editor is
   * showing rather than adding a tab. Unsaved work is protected first, because
   * clicking a file in a tree is not an obvious way to lose a paragraph.
   *
   * A figure is not editable, so it gets a preview where the editor would be --
   * enough to confirm the right chart was uploaded before referencing it.
   */
  const openTreeFile = async (pid, entry) => {
    if (entry.is_dir) return;
    if (pid === activeId && entry.path === openFile) return;

    // Save rather than ask. window.confirm is not implemented in the Tauri
    // webview -- it returns undefined, so `!confirm(...)` is true and switching
    // files while dirty would have been impossible. Silently losing the edit is
    // worse than silently keeping it, and keeping it is what an author expects
    // from a tree that autocompiles anyway.
    if (dirty) {
      try {
        if (openFile === 'main.tex') await papersApi.save(activeId, source);
        else await projectFilesApi.write(activeId, openFile, source);
        setDirty(false);
      } catch (e) {
        setError(`Could not save ${openFile}: ${e.message}`);
        return;
      }
    }

    // Clicking a file inside a different paper switches to that paper. The tree
    // is the only picker now, so opening a file has to be enough on its own.
    if (pid !== activeId) {
      await openProject(pid);
      if (entry.path === 'main.tex') return;   // openProject already loaded it
    }

    setError('');
    setStatus('');

    if (isImage(entry.name)) {
      setOpenFile(entry.path);
      setImagePath(entry.path);
      return;
    }

    // A PDF belongs in the preview pane -- that pane IS a PDF viewer, so
    // sending it to the editor and reading it as text only ever produced
    // "main.pdf is not a text file". main.pdf is also the compiler's own
    // output, so this is just "show me the last build".
    if (isPdf(entry.name)) {
      setOpenFile(entry.path);
      setImagePath(null);
      pdfVersion.current += 1;
      setPdfUrl(entry.path === 'main.pdf'
        ? `${papersApi.previewUrl(pid)}?v=${pdfVersion.current}`
        : `${projectFilesApi.rawUrl(pid, entry.path)}&v=${pdfVersion.current}`);
      return;
    }

    try {
      const d = await projectFilesApi.read(pid, entry.path);
      setImagePath(null);
      setOpenFile(entry.path);
      setSource(d.content || '');
      setDirty(false);
      // Only main.tex is what the compiler builds, so the "already compiled"
      // marker must not be set from some other file's contents -- doing so
      // would convince the autocompiler the document was up to date.
      if (entry.path === 'main.tex') compiledSrc.current = d.content || '';
    } catch (e) {
      setError(e.message);
    }
  };

  const handleSave = async () => {
    if (!activeId || imagePath) return;
    setBusy(true);
    setError('');
    try {
      clearTimeout(compileTimer.current);
      if (openFile === 'main.tex') {
        await papersApi.save(activeId, source);
        setDirty(false);
        flash('saved');
        // with autocompile on, don't make the user wait out the idle timer.
        // with it off, saving is just saving -- compiling is their call.
        if (autoCompile) compileNow(source);
      } else {
        // Any other file in the project: a section, a .bib, a .sty. Saving it
        // does not recompile on its own, because the document the compiler
        // builds is main.tex and this may not even be \input by it.
        await projectFilesApi.write(activeId, openFile, source);
        setDirty(false);
        flash('saved');
      }
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  /**
   * Save + compile. Used by the idle autocompile and by an explicit save.
   *
   * Compiling is the expensive part (a real TeX run), so it is guarded three
   * ways: never twice at once, never on unchanged source, and never sooner
   * than the idle delay below.
   */
  const compileNow = useCallback(async (src) => {
    if (!activeId || inFlight.current) return;
    if (compiledSrc.current === src) return;
    inFlight.current = true;
    setAutoStatus('compiling');
    setError('');
    try {
      await papersApi.save(activeId, src);
      setDirty(false);
      const res = await papersApi.compile(activeId);
      compiledSrc.current = src;
      pdfVersion.current += 1;
      setPdfUrl(`${papersApi.previewUrl(activeId)}?v=${pdfVersion.current}`);
      setWarnings(res?.warnings || []);
      setAutoStatus('ok');
      loadProjects();
    } catch (e) {
      // A compile error is normal while typing -- half-written LaTeX does not
      // build. Surface it without clearing the last good PDF, so the pane keeps
      // showing the last version that worked instead of going blank.
      setError(e.message);
      setAutoStatus('error');
    }
    inFlight.current = false;
  }, [activeId, loadProjects]);

  // Recompile a beat after typing stops. Long enough that a real TeX run does
  // not fire on every keystroke, short enough that the PDF feels live.
  useEffect(() => {
    if (!autoCompile) return undefined;
    if (!activeId || !source.trim()) return undefined;
    // ONLY while main.tex is the open file. `compileNow` saves through
    // papersApi.save, which writes main.tex by name -- so autocompiling while a
    // section file was open would quietly overwrite the document with the
    // contents of something else. Editing any other file is saved explicitly.
    if (openFile !== 'main.tex' || imagePath) return undefined;
    if (compiledSrc.current === source) return undefined;
    clearTimeout(compileTimer.current);
    compileTimer.current = setTimeout(() => compileNow(source), 2500);
    return () => clearTimeout(compileTimer.current);
  }, [source, activeId, autoCompile, compileNow, openFile, imagePath]);

  /**
   * Turn a request into LaTeX.
   *
   * Two ways in, one backend call:
   *
   *   - select prose in the editor and press Ctrl/Cmd+Enter. Whatever you
   *     selected IS the instruction, and the generated LaTeX replaces it in
   *     place. Writing "the graph of equation 1 goes here" and getting a
   *     pgfplots figure where those words were is the whole point.
   *   - type in the prompt box, and the result is appended before
   *     \end{document} as before.
   *
   * The model only ever sees the span plus the document for context and only
   * ever rewrites that span, which matters on a 0.5B: handing it the whole
   * paper to rewrite would mangle the LaTeX that already works.
   */
  const generateInto = useCallback(async (instruction, range) => {
    if (!activeId || !instruction.trim()) return;
    setGenerating(true);
    setError('');
    const before = source;
    try {
      // For a selection the insertion point is where it starts; for the prompt
      // box it is wherever the caret was left.
      const cursor = range
        ? range[0]
        : (editorRef.current ? editorRef.current.selectionStart : null);
      const d = await papersApi.generate(activeId, instruction.trim(), source, {
        docIds: groundDocs,
        cursor,
      });
      const latex = d.generated_latex || '';
      if (!latex.trim()) {
        setError('The model returned nothing. Try describing it more concretely.');
        setGenerating(false);
        return;
      }
      setUndoSrc(before);
      if (range) {
        const [from, to] = range;
        const next = before.slice(0, from) + latex + before.slice(to);
        setSource(next);
        // put the caret after what was just written, so typing continues
        // where the author was looking rather than jumping to the top
        requestAnimationFrame(() => {
          const el = editorRef.current;
          if (!el) return;
          el.focus();
          const caret = from + latex.length;
          el.setSelectionRange(caret, caret);
        });
        flash('rewritten as LaTeX');
      } else {
        // the caret the author last had in the editor, so a prompt-box request
        // is written where they are looking rather than at the end of the paper
        const caret = editorRef.current ? editorRef.current.selectionStart : undefined;
        const { text, caretAfter } = insertLatexAt(before, latex, caret);
        setSource(text);
        setPrompt('');
        requestAnimationFrame(() => {
          const el = editorRef.current;
          if (!el) return;
          el.focus();
          el.setSelectionRange(caretAfter, caretAfter);
        });
        flash('AI draft inserted at your cursor');
      }
      setDirty(true);
    } catch (e) {
      setError(e.message);
    }
    setGenerating(false);
  }, [activeId, source, groundDocs]);

  const handleGenerate = () => generateInto(prompt, null);

  /** Ctrl/Cmd+Enter in the editor: rewrite the selection as LaTeX. */
  const handleEditorKeyDown = (e) => {
    if (e.key !== 'Enter' || !(e.ctrlKey || e.metaKey)) return;
    const el = editorRef.current;
    if (!el) return;
    const { selectionStart: from, selectionEnd: to } = el;
    if (from === to) return; // nothing selected: let the newline through
    e.preventDefault();
    if (generating || llmBusy) return;
    generateInto(source.slice(from, to), [from, to]);
  };

  const undoAiEdit = () => {
    if (undoSrc === null) return;
    setSource(undoSrc);
    setUndoSrc(null);
    setDirty(true);
    flash('AI edit undone');
  };

  return (
    <div>
      <PageHeader
        title="Scribe"
      />

      {error && (
        <div className="toast error" style={{ position: 'static', margin: '0 0 1rem', whiteSpace: 'pre-wrap' }}>
          {error}
        </div>
      )}

      <div className="pw-grid" ref={gridRef}>
          {/* Papers AND their files, one tree. A project is a directory on disk,
              so it is a folder here -- which is also how \includegraphics can
              finally find a figure. One file open at a time, as in Overleaf. */}
          <FileTree
            projectId={activeId}
            openPath={openFile}
            onOpen={openTreeFile}
            onProjectGone={() => { setActiveId(null); setSource(''); setPdfUrl(null); }}
          />

          <div
            className="pw-split"
            onPointerDown={onTreeGrip}
            onKeyDown={onTreeGripKey}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the file tree"
            tabIndex={0}
          />

          {/* editor */}
          <motion.div
            className="card pw-editor"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring', stiffness: 240, damping: 28 }}
          >
            <div className="pw-toolbar">
              <span className="pw-toolbar-title">
                {openFile} {dirty && <span className="pw-dot" title="unsaved" />}
              </span>
              <div className="pw-toolbar-actions">
                {status && <span className="pw-status">{status}</span>}
                {!status && autoStatus === 'compiling' && (
                  <span className="pw-status"><Loader2 size={12} className="pw-spin" /> compiling…</span>
                )}
                {!status && autoStatus === 'ok' && autoCompile && (
                  <span className="pw-status">PDF up to date</span>
                )}
                {!status && autoStatus === 'error' && (
                  <span className="pw-status pw-status-err">LaTeX error - see below</span>
                )}

                <label className="pw-auto-toggle" title="Rebuild the PDF a moment after you stop typing">
                  <input
                    type="checkbox"
                    checked={autoCompile}
                    onChange={toggleAutoCompile}
                  />
                  <span>Auto</span>
                </label>

                <button className="btn btn-secondary btn-sm" onClick={handleSave} disabled={busy}>
                  <Save size={14} /> <span>Save</span>
                </button>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => { clearTimeout(compileTimer.current); compileNow(source); }}
                  disabled={busy || autoStatus === 'compiling'}
                  title={autoCompile ? 'Compile now instead of waiting' : 'Compile'}
                >
                  {autoStatus === 'compiling'
                    ? <Loader2 size={14} className="pw-spin" />
                    : <Play size={14} />}
                  <span>Compile</span>
                </button>
                {pdfUrl && (
                  <a className="btn btn-secondary btn-sm" href={papersApi.downloadUrl(activeId)} download>
                    <Download size={14} /> <span>PDF</span>
                  </a>
                )}
              </div>
            </div>

            {!activeId ? (
              /* The tree is always there, so this is never a dead end: it says
                 where to go rather than just reporting emptiness. */
              <div className="pw-empty">
                <FileText size={42} />
                <p>Pick a paper from the tree, or press + to start one.</p>
              </div>
            ) : imagePath ? (
              /* A figure is not editable. Showing it here -- where the editor
                 would be -- is what lets you confirm the right chart was
                 uploaded before you reference it in \includegraphics. */
              <div className="pw-imgview">
                <img
                  src={projectFilesApi.rawUrl(activeId, imagePath)}
                  alt={imagePath}
                />
                {/* the exact line to paste. Braces are escaped because a bare
                    {{ }} in JSX is an object literal, not two characters. */}
                <code>{`\\includegraphics[width=\\linewidth]{${imagePath}}`}</code>
              </div>
            ) : (
            <textarea
              ref={editorRef}
              className="pw-textarea"
              value={source}
              spellCheck={false}
              onChange={(e) => { setSource(e.target.value); setDirty(true); }}
              onKeyDown={handleEditorKeyDown}
              placeholder="Write plainly, select it, and press Ctrl+Enter to turn it into LaTeX."
            />
            )}
            <div className="pw-editor-hint">
              {generating
                ? 'Writing LaTeX…'
                : 'Select any plain-English line and press Ctrl+Enter to turn it into LaTeX.'}
              {undoSrc !== null && !generating && (
                <button type="button" className="pw-undo" onClick={undoAiEdit}>Undo AI edit</button>
              )}
            </div>

            <div className="pw-context">
              <button
                type="button"
                className="pw-context-toggle"
                onClick={() => setShowContext((v) => !v)}
              >
                <BookOpen size={14} />
                <span>Ground on papers{groundDocs.length ? ` · ${groundDocs.length} selected` : ''}</span>
                <ChevronDown size={14} className={showContext ? 'pw-rot' : ''} />
              </button>
              {showContext && (
                <div className="pw-context-list">
                  {docs.length === 0 ? (
                    <span className="pw-hint">no papers yet - upload in Library</span>
                  ) : (
                    docs.map((d) => (
                      <button
                        key={d.doc_id}
                        type="button"
                        className={`pw-chip ${groundDocs.includes(d.doc_id) ? 'active' : ''}`}
                        onClick={() => toggleGround(d.doc_id)}
                        title={d.filename}
                      >
                        <FileText size={13} />
                        <span>{d.filename}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>

            <div className="pw-ai">
              <Sparkles size={16} className="pw-ai-icon" />
              <textarea
                className="input pw-ai-input"
                rows={2}
                placeholder={llmBusy && !generating ? 'Model busy - please wait…' : 'Describe a section, equation, table, or chart for the AI to write… (Shift+Enter for a new line)'}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (!generating && !llmBusy && prompt.trim()) handleGenerate();
                  }
                }}
                disabled={llmBusy && !generating}
              />
              <button className="btn btn-primary" onClick={handleGenerate} disabled={generating || llmBusy || !prompt.trim()}>
                {generating || llmBusy ? <Loader2 size={16} className="pw-spin" /> : <Sparkles size={16} />}
                <span>{generating ? 'Generating…' : llmBusy && !generating ? (label || 'Model busy…') : 'Generate'}</span>
              </button>
            </div>
          </motion.div>

          {/* the compiled PDF is the only preview -- see the note at the top */}
          <div
            className="pw-split"
            onPointerDown={onPreviewGrip}
            onKeyDown={onPreviewGripKey}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the preview"
            tabIndex={0}
          />

          <div className="card pw-preview">
            <div className="pw-preview-tabs">
              <span className="pw-preview-tab active">
                <FileText size={14} /> Compiled PDF
              </span>
            </div>

            {warnings.length > 0 && (
              <details className="pw-warn">
                <summary>
                  ⚠ Compiled with {warnings.length} warning{warnings.length > 1 ? 's' : ''} - PDF may have missing figures
                </summary>
                <pre>{warnings.join('\n\n')}</pre>
              </details>
            )}

            <AnimatePresence mode="wait">
              {pdfUrl ? (
                <motion.iframe
                  key={pdfUrl}
                  title="compiled pdf"
                  src={pdfUrl}
                  className="pw-iframe"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.3 }}
                />
              ) : (
                <div className="pw-empty">
                  <FileText size={42} />
                  <p>{autoCompile
                    ? 'Start typing - the PDF builds itself.'
                    : 'Hit Compile to build the PDF.'}</p>
                </div>
              )}
            </AnimatePresence>
          </div>
      </div>
    </div>
  );
}
