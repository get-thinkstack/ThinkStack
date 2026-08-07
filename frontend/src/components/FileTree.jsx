/**
 * Every paper, and every file in it, as one tree.
 *
 * A project IS a directory on disk -- `data/papers_workspace/<id>/` with
 * `main.tex` inside it -- so it is a folder here too. Papers used to be a row
 * of chips above the editor, which meant two different pickers for two levels
 * of the same hierarchy, and no way at all to reach the second level. The chips
 * are gone; expanding a paper shows what is in it.
 *
 * That second level is the whole point: `\includegraphics{chart.png}` failed
 * not because the compiler was wrong -- it already runs with the project
 * directory as its working directory, so the relative path resolved -- but
 * because nothing could put a second file there.
 *
 * Conventions are borrowed, not invented, because a file tree is something
 * people already know: click opens, right-click offers actions, drop adds, F2
 * renames. The deliberate difference from VS Code is that one file is open at a
 * time, as in Overleaf; a tab strip would cost about 32px of height that the
 * editor and the PDF want for their halves of the window.
 *
 * Files load per paper, when it is expanded. A library of thirty papers should
 * not cost thirty requests to draw a list of names.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronDown, ChevronRight, File, FileImage, FileText, FilePlus2,
  FolderClosed, FolderOpen, FolderPlus, Loader2, Trash2, Upload,
} from 'lucide-react';
import { papersApi, projectFilesApi } from '../utils/api';
import { isImage } from '../utils/filekind';
import ConfirmDialog from './ConfirmDialog';

function iconFor(entry, expanded) {
  if (entry.is_dir) return expanded ? FolderOpen : FolderClosed;
  if (isImage(entry.name)) return FileImage;
  if (entry.name.toLowerCase().endsWith('.tex')) return FileText;
  return File;
}

function humanSize(n) {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** the flat list the API returns, nested for rendering. */
function nest(files) {
  const roots = [];
  const byPath = new Map();
  for (const f of files) {
    const node = { ...f, children: [] };
    byPath.set(f.path, node);
    const slash = f.path.lastIndexOf('/');
    if (slash === -1) roots.push(node);
    else {
      const parent = byPath.get(f.path.slice(0, slash));
      // a file whose parent is hidden has nowhere to go; putting it at the root
      // would claim it lives somewhere it does not
      if (parent) parent.children.push(node);
    }
  }
  return roots;
}

export default function FileTree({ projectId, openPath, onOpen, onProjectGone }) {
  const [projects, setProjects] = useState([]);
  const [filesBy, setFilesBy] = useState({});      // projectId -> files[]
  const [openProjects, setOpenProjects] = useState(() => new Set());
  const [openDirs, setOpenDirs] = useState(() => new Set());
  const [loading, setLoading] = useState(() => new Set());
  const [menu, setMenu] = useState(null);          // {x, y, kind, project, entry}
  const [renaming, setRenaming] = useState(null);  // `${projectId}:${path}` or `project:${id}`
  const [creating, setCreating] = useState(false);
  const [dropOn, setDropOn] = useState(null);      // projectId a drop would land in
  const [error, setError] = useState('');
  const [clipboard, setClipboard] = useState(null);
  const menuRef = useRef(null);
  // What is being created, and where. An inline row rather than window.prompt:
  // this runs in a Tauri webview, which does not implement prompt() -- it
  // returns null, so every "New file" quietly did nothing.
  const [pending, setPending] = useState(null);   // {kind, pid, dest}
  // Two-step delete, for the same reason: window.confirm is not available here
  // either, and a delete that cannot be confirmed must not be a delete that
  // happens anyway.
  const [confirming, setConfirming] = useState(null);

  const loadProjects = useCallback(async () => {
    try {
      const d = await papersApi.list();
      setProjects(d.projects || []);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  const loadFiles = useCallback(async (pid) => {
    setLoading((prev) => new Set(prev).add(pid));
    try {
      const d = await projectFilesApi.list(pid);
      setFilesBy((prev) => ({ ...prev, [pid]: d.files || [] }));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading((prev) => {
        const next = new Set(prev);
        next.delete(pid);
        return next;
      });
    }
  }, []);

  // The paper the editor has open is expanded for you -- it is the one you are
  // looking at, so hiding its files would be perverse.
  useEffect(() => {
    if (!projectId) return;
    setOpenProjects((prev) => (prev.has(projectId) ? prev : new Set(prev).add(projectId)));
    loadFiles(projectId);
  }, [projectId, loadFiles]);

  // Close on a press ELSEWHERE. The containment check is the whole point: this
  // listens in the capture phase (much of the tree stops propagation), and a
  // blind close would unmount the menu on pointerdown -- before the click ever
  // reached the button the user was pressing. Every item silently did nothing.
  useEffect(() => {
    if (!menu) return undefined;
    const onDown = (e) => {
      if (!menuRef.current?.contains(e.target)) setMenu(null);
    };
    const onKey = (e) => { if (e.key === 'Escape') setMenu(null); };
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('scroll', () => setMenu(null), true);
    return () => {
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [menu]);

  const adopt = (pid, res) => {
    if (res?.files) setFilesBy((prev) => ({ ...prev, [pid]: res.files }));
    return res;
  };

  const run = async (pid, fn) => {
    setError('');
    try {
      return adopt(pid, await fn());
    } catch (e) {
      setError(e.message);
      return null;
    }
  };

  const toggleProject = (pid) => {
    setOpenProjects((prev) => {
      const next = new Set(prev);
      if (next.has(pid)) next.delete(pid);
      else {
        next.add(pid);
        if (!filesBy[pid]) loadFiles(pid);
      }
      return next;
    });
  };

  const toggleDir = (key) =>
    setOpenDirs((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  // ── uploads: the button and the drop are the same operation ──
  const uploadInto = async (pid, list, dest = '') => {
    setError('');
    for (const file of list) {
      try {
        adopt(pid, await projectFilesApi.upload(pid, file, dest));
      } catch (e) {
        setError(e.message);
        break; // one rejection usually means the rest go the same way
      }
    }
  };

  const onDropInto = (e, pid) => {
    e.preventDefault();
    e.stopPropagation();
    setDropOn(null);
    const dropped = Array.from(e.dataTransfer?.files || []);
    if (!dropped.length) return;
    if (!openProjects.has(pid)) toggleProject(pid);
    uploadInto(pid, dropped);
  };

  // ── papers ──
  const createProject = async (name) => {
    setPending(null);
    const clean = (name || '').trim();
    if (!clean) return;
    setCreating(true);
    try {
      const d = await papersApi.create(clean);
      await loadProjects();
      setOpenProjects((prev) => new Set(prev).add(d.project_id));
      loadFiles(d.project_id);
      onOpen?.(d.project_id, { path: 'main.tex', name: 'main.tex', is_dir: false });
    } catch (e) {
      setError(e.message);
    }
    setCreating(false);
  };

  const renameProject = async (p, name) => {
    setRenaming(null);
    const clean = (name || '').trim();
    if (!clean || clean === p.name) return;
    try {
      await papersApi.rename(p.project_id, clean);
      await loadProjects();
    } catch (e) {
      setError(e.message);
    }
  };

  const deleteProject = async (p) => {
    setConfirming(null);
    try {
      await papersApi.remove(p.project_id);
      await loadProjects();
      setFilesBy((prev) => {
        const next = { ...prev };
        delete next[p.project_id];
        return next;
      });
      if (p.project_id === projectId) onProjectGone?.();
    } catch (e) {
      setError(e.message);
    }
  };

  // ── files ──
  /**
   * Begin creating something, and make sure the row will be VISIBLE.
   *
   * The input renders inside the folder it belongs to, so a collapsed parent
   * means an input nobody can see -- the menu item would look broken in exactly
   * the way `window.prompt` did. Expanding is therefore part of starting, not
   * part of finishing.
   */
  const startCreate = (kind, pid, dest = '') => {
    setMenu(null);
    if (pid && !openProjects.has(pid)) toggleProject(pid);
    if (pid && dest) {
      // every ancestor, not just the immediate parent: creating inside
      // figures/charts must open `figures` too or the row is still hidden
      setOpenDirs((prev) => {
        const next = new Set(prev);
        const parts = dest.split('/');
        for (let i = 1; i <= parts.length; i += 1) {
          next.add(`${pid}:${parts.slice(0, i).join('/')}`);
        }
        return next;
      });
    }
    setPending({ kind, pid, dest });
  };

  /** commit an inline "new file"/"new folder" row. */
  const commitPending = (name) => {
    const req = pending;
    setPending(null);
    const clean = (name || '').trim();
    if (!req || !clean) return;
    if (req.kind === 'project') return createProject(clean);
    const path = req.dest ? `${req.dest}/${clean}` : clean;
    return run(req.pid, () => (req.kind === 'folder'
      ? projectFilesApi.mkdir(req.pid, path)
      : projectFilesApi.write(req.pid, path, '')));
  };

  const deleteEntry = (pid, entry) => {
    setConfirming(null);
    run(pid, () => projectFilesApi.remove(pid, entry.path));
  };

  const duplicate = (pid, entry) => {
    const dot = entry.name.lastIndexOf('.');
    const copy = dot > 0
      ? `${entry.name.slice(0, dot)} copy${entry.name.slice(dot)}`
      : `${entry.name} copy`;
    const parent = entry.path.includes('/') ? `${entry.path.slice(0, entry.path.lastIndexOf('/'))}/` : '';
    run(pid, () => projectFilesApi.copy(pid, entry.path, parent + copy));
  };

  const commitRename = (pid, entry, nextName) => {
    setRenaming(null);
    const trimmed = (nextName || '').trim();
    if (!trimmed || trimmed === entry.name) return;
    const parent = entry.path.includes('/') ? `${entry.path.slice(0, entry.path.lastIndexOf('/'))}/` : '';
    run(pid, () => projectFilesApi.move(pid, entry.path, parent + trimmed));
  };

  /**
   * The row you type a name into.
   *
   * This exists instead of window.prompt because ThinkStack runs in a Tauri
   * webview, where prompt() is not implemented and simply returns null -- so
   * every "New file" appeared to do nothing at all. It is also just better:
   * the name appears where the file will.
   */
  const nameRow = (placeholder, onCommit, depth = 1) => (
    <div className="ft-row is-input" style={{ paddingLeft: `${10 + depth * 12}px` }}>
      <span className="ft-caret-space" />
      <input
        className="ft-rename"
        autoFocus
        placeholder={placeholder}
        onBlur={(e) => onCommit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onCommit(e.target.value);
          if (e.key === 'Escape') { setPending(null); setRenaming(null); }
        }}
      />
    </div>
  );

  // ── rows ──
  const renderEntry = (pid, entry, depth) => {
    const key = `${pid}:${entry.path}`;
    const isDirOpen = openDirs.has(key);
    const Icon = iconFor(entry, isDirOpen);
    const isCurrent = pid === projectId && openPath === entry.path;

    return (
      <div key={key}>
        <div
          className={`ft-row ${isCurrent ? 'is-open' : ''}`}
          style={{ paddingLeft: `${10 + depth * 12}px` }}
          onClick={() => (entry.is_dir ? toggleDir(key) : onOpen?.(pid, entry))}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setMenu({ x: e.clientX, y: e.clientY, kind: 'entry', pid, entry });
          }}
          onKeyDown={(e) => {
            if (e.key === 'F2') { e.preventDefault(); setRenaming(key); }
            if (e.key === 'Enter') (entry.is_dir ? toggleDir(key) : onOpen?.(pid, entry));
          }}
          role="button"
          tabIndex={0}
          title={entry.path}
        >
          {entry.is_dir
            ? (isDirOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />)
            : <span className="ft-caret-space" />}
          <Icon size={13} className="ft-icon" />
          {renaming === key ? (
            <input
              className="ft-rename"
              defaultValue={entry.name}
              autoFocus
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => commitRename(pid, entry, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename(pid, entry, e.target.value);
                if (e.key === 'Escape') setRenaming(null);
              }}
            />
          ) : (
            <>
              <span className="ft-name">{entry.name}</span>
              {!entry.is_dir && <span className="ft-size">{humanSize(entry.size)}</span>}
            </>
          )}
        </div>
        {entry.is_dir && isDirOpen && (
          <>
            {entry.children.map((c) => renderEntry(pid, c, depth + 1))}
            {pending?.pid === pid && pending.dest === entry.path && nameRow(
              pending.kind === 'folder' ? 'folder name' : 'name.tex',
              commitPending,
              depth + 1,
            )}
          </>
        )}
      </div>
    );
  };

  const renderProject = (p) => {
    const pid = p.project_id;
    const isOpen = openProjects.has(pid);
    const isActive = pid === projectId;
    const files = filesBy[pid] || [];

    return (
      <div
        key={pid}
        className={`ft-project ${dropOn === pid ? 'is-dropping' : ''}`}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDropOn(pid); }}
        onDragLeave={(e) => { e.stopPropagation(); setDropOn(null); }}
        onDrop={(e) => onDropInto(e, pid)}
      >
        <div
          className={`ft-row is-project ${isActive ? 'is-active' : ''}`}
          onClick={() => toggleProject(pid)}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setMenu({ x: e.clientX, y: e.clientY, kind: 'project', pid, project: p });
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') toggleProject(pid);
            if (e.key === 'F2') { e.preventDefault(); setRenaming(`project:${pid}`); }
          }}
          role="button"
          tabIndex={0}
          title={p.name}
        >
          {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {isOpen ? <FolderOpen size={13} className="ft-icon" /> : <FolderClosed size={13} className="ft-icon" />}
          {renaming === `project:${pid}` ? (
            <input
              className="ft-rename"
              defaultValue={p.name}
              autoFocus
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => renameProject(p, e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === 'Enter') renameProject(p, e.target.value);
                if (e.key === 'Escape') setRenaming(null);
              }}
            />
          ) : (
            <span className="ft-name">{p.name}</span>
          )}
          {loading.has(pid) && <Loader2 size={11} className="ft-spin" />}
          {p.has_pdf && !loading.has(pid) && !renaming && <span className="ft-dot" title="compiled" />}
        </div>

        {isOpen && (
          <>
            {nest(files).map((e) => renderEntry(pid, e, 1))}
            {pending?.pid === pid && !pending.dest && nameRow(
              pending.kind === 'folder' ? 'folder name' : 'name.tex',
              commitPending,
            )}
            {!files.length && !loading.has(pid) && !pending
              && <p className="ft-empty ft-indent">empty</p>}
          </>
        )}
      </div>
    );
  };

  return (
    <div className="ft" onDragLeave={() => setDropOn(null)}>
      <div className="ft-head">
        <span className="ft-title">Papers</span>
        <div className="ft-head-actions">
          <button
            type="button"
            title="New paper"
            onClick={() => startCreate('project')}
            disabled={creating}
          >
            {creating ? <Loader2 size={14} className="ft-spin" /> : <FilePlus2 size={14} />}
          </button>
        </div>
      </div>

      <div className="ft-list">
        {projects.map(renderProject)}
        {pending?.kind === 'project' && nameRow('paper name', commitPending, 0)}
        {projects.length === 0 && !pending
          && <p className="ft-empty">No papers yet. Press + to start one.</p>}
      </div>

      {error && <p className="ft-error">{error}</p>}

      {confirming && (
        <ConfirmDialog
          title={confirming.kind === 'project'
            ? `Delete “${confirming.project.name}”?`
            : `Delete ${confirming.entry.name}?`}
          body={confirming.kind === 'project'
            ? 'The paper and every file in it are removed from disk. This cannot be undone.'
            : confirming.entry.is_dir
              ? 'The folder and everything inside it are removed from disk. This cannot be undone.'
              : 'The file is removed from disk. This cannot be undone.'}
          onCancel={() => setConfirming(null)}
          onConfirm={() => (confirming.kind === 'project'
            ? deleteProject(confirming.project)
            : deleteEntry(confirming.pid, confirming.entry))}
        />
      )}

      {menu && (
        <div className="ft-menu" ref={menuRef} style={{ left: menu.x, top: menu.y }}>
          {menu.kind === 'project' ? (
            <>
              <button type="button" onClick={() => { toggleProject(menu.pid); setMenu(null); }}>
                {openProjects.has(menu.pid) ? 'Collapse' : 'Expand'}
              </button>
              <div className="ft-menu-sep" />
              <button
                type="button"
                onClick={() => startCreate('file', menu.pid)}
              >
                <FilePlus2 size={12} /> New file
              </button>
              <button
                type="button"
                onClick={() => startCreate('folder', menu.pid)}
              >
                <FolderPlus size={12} /> New folder
              </button>
              <button
                type="button"
                onClick={() => { setRenaming(`project:${menu.pid}`); setMenu(null); }}
              >
                Rename paper <span className="ft-menu-key">F2</span>
              </button>
              <label className="ft-menu-upload">
                <Upload size={12} /> Upload…
                <input
                  type="file"
                  multiple
                  onChange={(e) => {
                    uploadInto(menu.pid, Array.from(e.target.files || []));
                    e.target.value = '';
                    setMenu(null);
                  }}
                />
              </label>
              <button
                type="button"
                disabled={!clipboard}
                onClick={() => {
                  const c = clipboard;
                  if (c) run(menu.pid, () => projectFilesApi.copy(menu.pid, c.entry.path, c.entry.name));
                  setMenu(null);
                }}
              >
                Paste
              </button>
              <div className="ft-menu-sep" />
              <button
                type="button"
                className="is-danger"
                onClick={() => { setConfirming({ kind: 'project', project: menu.project }); setMenu(null); }}
              >
                <Trash2 size={12} /> Delete paper
              </button>
            </>
          ) : (
            <>
              {!menu.entry.is_dir && (
                <button type="button" onClick={() => { onOpen?.(menu.pid, menu.entry); setMenu(null); }}>Open</button>
              )}
              <button type="button" onClick={() => { setRenaming(`${menu.pid}:${menu.entry.path}`); setMenu(null); }}>
                Rename <span className="ft-menu-key">F2</span>
              </button>
              <button type="button" onClick={() => { duplicate(menu.pid, menu.entry); setMenu(null); }}>Duplicate</button>
              <button type="button" onClick={() => { setClipboard({ pid: menu.pid, entry: menu.entry }); setMenu(null); }}>
                Copy
              </button>
              <div className="ft-menu-sep" />
              <button
                type="button"
                onClick={() => startCreate('file', menu.pid, menu.entry.is_dir ? menu.entry.path : '')}
              >
                New file
              </button>
              <button
                type="button"
                onClick={() => startCreate('folder', menu.pid, menu.entry.is_dir ? menu.entry.path : '')}
              >
                New folder
              </button>
              <div className="ft-menu-sep" />
              <button
                type="button"
                className="is-danger"
                onClick={() => { setConfirming({ kind: 'entry', pid: menu.pid, entry: menu.entry }); setMenu(null); }}
              >
                <Trash2 size={12} /> Delete
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
