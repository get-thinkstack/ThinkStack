/**
 * LatexPreview — real-time client-side LaTeX → HTML renderer.
 *
 * Converts common LaTeX structural commands to styled HTML and uses KaTeX
 * for math expressions. Runs entirely in the browser — no pdflatex needed.
 *
 * Supports: sections, lists, math, tables, formatting, abstract, title block.
 */

import { useMemo, useState, useEffect } from 'react';

/* KaTeX is loaded lazily at runtime. If not installed (npm install katex),
   math expressions fall back to styled <code> blocks. */
let _katex = null;
let _katexLoaded = false;
let _katexPromise = null;

function loadKatex() {
  if (_katexPromise) return _katexPromise;
  _katexPromise = import(/* @vite-ignore */ 'katex')
    .then((mod) => {
      _katex = mod.default || mod;
      _katexLoaded = true;
      return import(/* @vite-ignore */ 'katex/dist/katex.min.css');
    })
    .catch(() => { _katexLoaded = true; /* mark as attempted */ });
  return _katexPromise;
}

/* ------------------------------------------------------------------ */
/*  KaTeX helpers                                                      */
/* ------------------------------------------------------------------ */

function renderMath(tex, displayMode = false) {
  if (!_katex) {
    // fallback: show raw math in a styled code block
    const escaped = escHtml(tex.trim());
    return displayMode
      ? `<code class="lp-math-fallback">${escaped}</code>`
      : `<code class="lp-math-fallback lp-math-inline">${escaped}</code>`;
  }
  try {
    return _katex.renderToString(tex.trim(), {
      displayMode,
      throwOnError: false,
      trust: true,
      strict: false,
    });
  } catch {
    return `<code class="lp-math-err">${escHtml(tex)}</code>`;
  }
}

function escHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* ------------------------------------------------------------------ */
/*  LaTeX → HTML converter                                             */
/* ------------------------------------------------------------------ */

function latexToHtml(source) {
  if (!source || !source.trim()) return '';

  let text = source;

  // ── strip preamble ───────────────────────────────────────────────
  // remove everything before \begin{document} and the tag itself
  const beginDoc = text.indexOf('\\begin{document}');
  if (beginDoc !== -1) text = text.slice(beginDoc + '\\begin{document}'.length);
  const endDoc = text.indexOf('\\end{document}');
  if (endDoc !== -1) text = text.slice(0, endDoc);

  // strip \usepackage, \documentclass, \pgfplotsset, etc.
  text = text.replace(/\\(documentclass|usepackage|pgfplotsset|usetikzlibrary|geometry)\b[^\n]*/g, '');

  // ── extract title block metadata ─────────────────────────────────
  let title = '', author = '', date = '';
  text = text.replace(/\\title\{([^}]*)\}/g, (_, t) => { title = t; return ''; });
  text = text.replace(/\\author\{([^}]*)\}/g, (_, a) => { author = a; return ''; });
  text = text.replace(/\\date\{([^}]*)\}/g, (_, d) => { date = d; return ''; });
  text = text.replace(/\\maketitle/g, '');

  let titleHtml = '';
  if (title || author || date) {
    titleHtml = '<div class="lp-titleblock">';
    if (title)  titleHtml += `<h1 class="lp-title">${processInline(title)}</h1>`;
    if (author) titleHtml += `<div class="lp-author">${processInline(author)}</div>`;
    if (date)   titleHtml += `<div class="lp-date">${processInline(date)}</div>`;
    titleHtml += '</div>';
  }

  // ── display math environments ────────────────────────────────────
  // equation, align, gather, multline — render as display math
  text = text.replace(
    /\\begin\{(equation|align|gather|multline)\*?\}([\s\S]*?)\\end\{\1\*?\}/g,
    (_, _env, body) => `<div class="lp-display-math">${renderMath(body, true)}</div>`
  );

  // $$ ... $$ display math
  text = text.replace(/\$\$([\s\S]*?)\$\$/g,
    (_, body) => `<div class="lp-display-math">${renderMath(body, true)}</div>`
  );

  // \[ ... \] display math
  text = text.replace(/\\\[([\s\S]*?)\\\]/g,
    (_, body) => `<div class="lp-display-math">${renderMath(body, true)}</div>`
  );

  // ── abstract ─────────────────────────────────────────────────────
  text = text.replace(
    /\\begin\{abstract\}([\s\S]*?)\\end\{abstract\}/g,
    (_, body) => `<div class="lp-abstract"><h3>Abstract</h3><p>${processInline(body.trim())}</p></div>`
  );

  // ── sections ─────────────────────────────────────────────────────
  text = text.replace(/\\section\*?\{([^}]*)\}/g,
    (_, t) => `<h2 class="lp-section">${processInline(t)}</h2>`);
  text = text.replace(/\\subsection\*?\{([^}]*)\}/g,
    (_, t) => `<h3 class="lp-subsection">${processInline(t)}</h3>`);
  text = text.replace(/\\subsubsection\*?\{([^}]*)\}/g,
    (_, t) => `<h4 class="lp-subsubsection">${processInline(t)}</h4>`);
  text = text.replace(/\\paragraph\*?\{([^}]*)\}/g,
    (_, t) => `<p><strong>${processInline(t)}</strong></p>`);

  // ── lists ────────────────────────────────────────────────────────
  text = text.replace(
    /\\begin\{(itemize|enumerate)\}([\s\S]*?)\\end\{\1\}/g,
    (_, type, body) => {
      const tag = type === 'enumerate' ? 'ol' : 'ul';
      const items = body.split(/\\item\b/).filter(s => s.trim());
      const lis = items.map(i => `<li>${processInline(i.trim())}</li>`).join('\n');
      return `<${tag} class="lp-list">${lis}</${tag}>`;
    }
  );

  // ── figures / tikz / tables — show a styled placeholder ──────────
  text = text.replace(
    /\\begin\{figure\}[\s\S]*?\\end\{figure\}/g,
    '<div class="lp-placeholder">[Figure — compile to view]</div>'
  );
  text = text.replace(
    /\\begin\{tikzpicture\}[\s\S]*?\\end\{tikzpicture\}/g,
    '<div class="lp-placeholder">[TikZ diagram — compile to view]</div>'
  );

  // simple tabular → HTML table
  text = text.replace(
    /\\begin\{(?:table\}[\s\S]*?\\begin\{)?tabular[x]?\}\{[^}]*\}([\s\S]*?)\\end\{tabular[x]?\}([\s\S]*?\\end\{table\})?/g,
    (_, body) => {
      const rows = body
        .split(/\\\\/)
        .map(r => r.replace(/\\(?:toprule|midrule|bottomrule|hline|cmidrule\{[^}]*\})/g, '').trim())
        .filter(r => r);
      if (!rows.length) return '<div class="lp-placeholder">[Table — compile to view]</div>';
      const html = rows.map((row, i) => {
        const cells = row.split('&').map(c => processInline(c.trim()));
        const tag = i === 0 ? 'th' : 'td';
        return `<tr>${cells.map(c => `<${tag}>${c}</${tag}>`).join('')}</tr>`;
      }).join('\n');
      return `<table class="lp-table">${html}</table>`;
    }
  );

  // ── footnotes ────────────────────────────────────────────────────
  text = text.replace(/\\footnote\{([^}]*)\}/g,
    (_, body) => `<sup class="lp-footnote" title="${escHtml(body)}">[*]</sup>`);

  // ── citations / refs ─────────────────────────────────────────────
  text = text.replace(/\\(?:cite[pt]?|citep|citet)\{([^}]*)\}/g,
    (_, keys) => `<span class="lp-cite">[${escHtml(keys)}]</span>`);
  text = text.replace(/\\(?:ref|eqref|label)\{([^}]*)\}/g,
    (_, key) => `<span class="lp-ref">[${escHtml(key)}]</span>`);

  // ── inline formatting ────────────────────────────────────────────
  text = processInline(text);

  // ── paragraphs ───────────────────────────────────────────────────
  // double newlines → <p> breaks  (skip if already inside HTML tags)
  text = text.replace(/\n{2,}/g, '</p><p>');

  // strip leftover \commands that weren't handled
  text = text.replace(/\\(?:vspace|hspace|clearpage|newpage|noindent|bigskip|medskip|smallskip)\b[^a-zA-Z]*/g, '');
  text = text.replace(/\\(?:centering|raggedright|raggedleft)\b/g, '');

  // strip leftover comments
  text = text.replace(/(?:^|\n)%[^\n]*/g, '');

  return `${titleHtml}<div class="lp-body"><p>${text}</p></div>`;
}

/** Process inline LaTeX commands: bold, italic, math, etc. */
function processInline(text) {
  if (!text) return '';

  // inline math: $...$  (but not $$)
  text = text.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g,
    (_, m) => renderMath(m, false));

  // \( ... \) inline math
  text = text.replace(/\\\((.+?)\\\)/g,
    (_, m) => renderMath(m, false));

  // \textbf{...}
  text = text.replace(/\\textbf\{([^}]*)\}/g, '<strong>$1</strong>');
  // \textit{...}  and \emph{...}
  text = text.replace(/\\(?:textit|emph)\{([^}]*)\}/g, '<em>$1</em>');
  // \underline{...}
  text = text.replace(/\\underline\{([^}]*)\}/g, '<u>$1</u>');
  // \texttt{...}
  text = text.replace(/\\texttt\{([^}]*)\}/g, '<code>$1</code>');
  // \text{...} (inside math context or otherwise)
  text = text.replace(/\\text\{([^}]*)\}/g, '$1');
  // \url{...}
  text = text.replace(/\\url\{([^}]*)\}/g, '<a href="$1" class="lp-url">$1</a>');
  // \href{url}{text}
  text = text.replace(/\\href\{([^}]*)\}\{([^}]*)\}/g, '<a href="$1" class="lp-url">$2</a>');

  // ~ → non-breaking space, \\ → <br>, -- → en-dash, --- → em-dash
  text = text.replace(/~/g, '&nbsp;');
  text = text.replace(/\\\\/g, '<br/>');
  text = text.replace(/---/g, '—');
  text = text.replace(/--/g, '–');

  return text;
}

/* ------------------------------------------------------------------ */
/*  React component                                                    */
/* ------------------------------------------------------------------ */

export default function LatexPreview({ source }) {
  const [, setReady] = useState(false);

  // trigger lazy KaTeX load on mount; re-render once loaded
  useEffect(() => {
    loadKatex().then(() => setReady(true));
  }, []);

  const html = useMemo(() => latexToHtml(source), [source, _katexLoaded]);

  if (!source || !source.trim()) {
    return (
      <div className="lp-empty">
        <p>Start writing LaTeX to see the preview here.</p>
      </div>
    );
  }

  return (
    <div className="lp-root">
      <div className="lp-content" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
