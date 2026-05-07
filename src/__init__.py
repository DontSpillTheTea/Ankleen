"""
Gemini LaTeX Fixer for Anki
A non-destructive, one-click editor tool to safely convert $...$ and $$...$$ LaTeX delimiters
and clean up AI-generated Markdown formatting.
"""

import re
import html
import difflib

from aqt import gui_hooks
from aqt.editor import Editor
from aqt.utils import tooltip
from aqt.qt import (
    QDialog, QVBoxLayout, QDialogButtonBox,
    QTabWidget, QTextBrowser, QPlainTextEdit,
    QColor, QPalette,
)


# ---------------------------------------------------------------------------
# Core conversion logic
# ---------------------------------------------------------------------------

_DISPLAY_MATH = re.compile(
    r'\$\$'        # opening $$
    r'(.*?)'       # content (non-greedy)
    r'\$\$',       # closing $$
    re.DOTALL
)

_INLINE_MATH = re.compile(
    r'(?<!\$)'            # not preceded by $
    r'(?<!\\)'            # not preceded by \
    r'\$'                 # opening $
    r'(?!\s)'             # not followed by space
    r'([^$\n]+?)'         # content
    r'(?<!\s)'            # not preceded by space
    r'\$'                 # closing $
    r'(?!\$)'             # not followed by $
)

SAFE_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 's', 'del', 'code',
    'br', 'div', 'span', 'p',
    'ul', 'ol', 'li',
    'sub', 'sup',
    'img', 'a',
    'font',
    'table', 'tr', 'td', 'th', 'tbody', 'thead',
    'anki-mathjax', 'hr',
    # NOTE: 'script' and 'style' intentionally excluded.
}

# Markdown regexes for text nodes
_MD_BOLD1 = re.compile(r'\*\*([^*]+?)\*\*')
_MD_BOLD2 = re.compile(r'(^|[\s\W])__(?![a-zA-Z0-9]+__)([^_]+?)__([\s\W]|$)')
_MD_STRIKE1 = re.compile(r'~~([^~]+?)~~')
_MD_STRIKE2 = re.compile(r'(?<!~)~([^~]+?)~(?!=~)')


def process_math_content(content: str) -> tuple[str, bool]:
    """
    Returns (new_content, is_unicode_converted).
    If it's successfully converted to simple Unicode, the caller can drop the MathJax delimiters.
    """
    original = content.strip()
    text = original
    
    # 1. Simple replacements for set theory & probability
    text = text.replace(r'\cup', '∪')
    text = text.replace(r'\cap', '∩')
    text = text.replace(r' \mid ', '|')   # space-padded: P(A \mid B) -> P(A|B)
    text = text.replace(r'\mid', '|')     # unpadded fallback
    
    # 2. Fractions: \frac{A}{B} -> A / B
    text = re.sub(r'\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}', r'\1 / \2', text)
    
    # 3. Check for remaining LaTeX macros or complex structures
    if any(c in text for c in ('\\', '_', '^', '{', '}')):
        return original, False
        
    return text, True

# ---------------------------------------------------------------------------
# Code span sentinels — private-use Unicode; virtually impossible in real notes
# ---------------------------------------------------------------------------

_CODE_PREFIX = "\uE000ANKLEEN_CODE_"
_CODE_SUFFIX = "_\uE001"


def _code_token(index: int) -> str:
    return f"{_CODE_PREFIX}{index}{_CODE_SUFFIX}"


def _repair_code_span_artifacts(code: str) -> str:
    """Remove browser-duplicated fake HTML tags that appear after escaped literals.

    When a user imports/types  `static_cast&lt;double&gt;(x)`  the browser may
    parse <double> as a real tag and insert it into the source, giving:
        static_cast&lt;double&gt;<double>(x)
    We detect the pattern  &lt;TAG&gt;<TAG>  and collapse it to just &lt;TAG&gt;.
    Handles both opening and closing template-style duplicates.
    """
    # &lt;Tag&gt;<Tag>  →  &lt;Tag&gt;
    code = re.sub(
        r'(&lt;([A-Za-z_][A-Za-z0-9_:,. -]*)&gt;)<\2>',
        r'\1',
        code,
    )
    # &lt;/Tag&gt;</Tag>  →  &lt;/Tag&gt;
    code = re.sub(
        r'(&lt;/([A-Za-z_][A-Za-z0-9_:,. -]*)&gt;)</\2>',
        r'\1',
        code,
    )
    return code


# Matches `...` and greedily consumes any orphan closing tags for UNKNOWN tags
# immediately after the closing backtick. Safe tags like </div> are NOT consumed.
_UNKNOWN_TAG_ORPHAN_RE = re.compile(
    r"</(?!(?:" + "|".join(SAFE_TAGS) + r")(?=>))[A-Za-z_][A-Za-z0-9_:.-]*>"
)
_CODE_SPAN_RE = re.compile(
    r"`([^`\n]+?)`"
)


def _protect_code_spans(text: str) -> tuple[str, list[str]]:
    """Replace all `...` spans with sentinel tokens. Content is HTML-escaped idempotently.

    Also repairs browser artifact patterns:
    - Duplicated fake tags inside the code span  (e.g. &lt;T&gt;<T>)
    - Orphan closing tags immediately after the closing backtick  (e.g. `code`</T>)
    """
    code_spans: list[str] = []

    def repl(m):
        code = m.group(1)
        # Remove browser-injected duplicate tag artifacts from inside the code span
        code = _repair_code_span_artifacts(code)
        # Orphan closing tags after the backtick are simply dropped (they are
        # artifacts — valid inline code is never followed by a raw closing tag)
        raw = html.unescape(code)
        escaped = html.escape(raw, quote=False)
        tok = _code_token(len(code_spans))
        code_spans.append(f"<code>{escaped}</code>")
        return tok

    def repl_with_orphan_cleanup(m_text):
        # After extracting code spans, strip lingering unknown closing tags
        return _UNKNOWN_TAG_ORPHAN_RE.sub("", m_text)

    protected = _CODE_SPAN_RE.sub(repl, text)
    protected = _UNKNOWN_TAG_ORPHAN_RE.sub("", protected)
    return protected, code_spans


def _restore_code_spans(text: str, code_spans: list[str]) -> str:
    """Substitute sentinel tokens back with their <code>...</code> HTML."""
    for i, span_html in enumerate(code_spans):
        text = text.replace(_code_token(i), span_html)
    return text


def fix_formatting(html_field: str) -> str:
    """Convert $/$$ delimiters and safely process Markdown and HTML."""
    text = html_field

    # --- 0. Protect inline code FIRST ---
    # Must happen before math, tag stripping, or any other regex.
    # Code content can contain $, <T>, _, ^, &, | — all of which
    # would be mangled by later passes if not protected.
    #
    # Also repair the browser artifact <tag>`</tag> -> ` before extracting.
    text = re.sub(r'<([a-zA-Z0-9_]+)>`</\1>', r'`', text)
    text, code_spans = _protect_code_spans(text)

    # --- 1. Math Delimiters ---
    def repl_display(m):
        new_content, is_simple = process_math_content(m.group(1))
        return new_content if is_simple else f'\\[{m.group(1)}\\]'

    def repl_inline(m):
        new_content, is_simple = process_math_content(m.group(1))
        return new_content if is_simple else f'\\({m.group(1)}\\)'

    text = _DISPLAY_MATH.sub(repl_display, text)
    text = _INLINE_MATH.sub(repl_inline, text)

    # --- 2. Strip Unknown Artifact Tags ---
    def repl_tag(m):
        full_tag = m.group(0)
        tag_name = m.group(1).lower()
        if tag_name in SAFE_TAGS:
            return full_tag
        return ""

    text = re.sub(r'</?([a-zA-Z0-9\-]+)[^>]*>', repl_tag, text)

    # --- 3. Markdown on Text Nodes Only ---
    tokens = re.split(r'(<[^>]+>)', text)
    for i in range(len(tokens)):
        if tokens[i].startswith('<') and tokens[i].endswith('>'):
            continue  # skip HTML tags
        t = tokens[i]
        t = _MD_BOLD1.sub(r'<b>\1</b>', t)
        t = _MD_BOLD2.sub(r'\1<b>\2</b>\3', t)
        t = _MD_STRIKE1.sub(r'<s>\1</s>', t)
        t = _MD_STRIKE2.sub(r'<s>\1</s>', t)
        tokens[i] = t
    text = "".join(tokens)

    # --- 4. Normalize Spacing ---
    text = re.sub(r'(?:<br\s*/?>|\n|\r)+', '<br><br>', text, flags=re.IGNORECASE)
    text = re.sub(r'^(?:<br\s*/?>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:<br\s*/?>)+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>\s*<div>', '</div><br><br><div>', text, flags=re.IGNORECASE)

    # --- 5. Restore Protected Code Spans (always last) ---
    text = _restore_code_spans(text, code_spans)

    return text


# ---------------------------------------------------------------------------
# Editor integration
# ---------------------------------------------------------------------------

_undo_history = {}  # note_key -> list of previous fields

def _get_note_key(note):
    return note.id if note.id else id(note)


def _blend(c1: QColor, c2: QColor, amount: float) -> QColor:
    """Linear blend: amount=0 returns c1, amount=1 returns c2."""
    amount = max(0.0, min(1.0, amount))
    r = round(c1.red()   * (1 - amount) + c2.red()   * amount)
    g = round(c1.green() * (1 - amount) + c2.green() * amount)
    b = round(c1.blue()  * (1 - amount) + c2.blue()  * amount)
    return QColor(r, g, b)


def _is_dark(c: QColor) -> bool:
    """Perceived brightness check."""
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) < 128


def _preview_colors(widget) -> dict:
    """Return theme-aware CSS color strings, including subtle red/green tints."""
    pal = widget.palette()
    base   = pal.color(QPalette.ColorRole.Base)
    text   = pal.color(QPalette.ColorRole.Text)
    window = pal.color(QPalette.ColorRole.Window)
    border = pal.color(QPalette.ColorRole.Mid)

    dark = _is_dark(base)
    tint  = 0.18 if dark else 0.08   # more lift needed in dark mode

    before_bg     = _blend(base,   QColor(180, 60,  60),  tint)
    after_bg      = _blend(base,   QColor(60,  150, 80),  tint)
    before_border = _blend(border, QColor(220, 80,  80),  0.35)
    after_border  = _blend(border, QColor(80,  190, 110), 0.35)

    return {
        "window":        window.name(),
        "text":          text.name(),
        "border":        border.name(),
        "before_bg":     before_bg.name(),
        "after_bg":      after_bg.name(),
        "before_border": before_border.name(),
        "after_border":  after_border.name(),
    }


def _build_rendered_html(old_fields, new_fields, field_names, colors):
    """Build readable before/after HTML for the Rendered Preview tab."""
    c = colors  # shorthand
    head = (
        f"<html><head><style>"
        f"body {{ background:{c['window']}; color:{c['text']}; font-family:sans-serif; margin:8px; }}"
        f".box {{ border-radius:6px; padding:8px; margin-bottom:6px; color:{c['text']}; }}"
        f".before {{ background:{c['before_bg']}; border:1px solid {c['before_border']}; border-left:4px solid {c['before_border']}; }}"
        f".after  {{ background:{c['after_bg']};  border:1px solid {c['after_border']};  border-left:4px solid {c['after_border']};  }}"
        f".label  {{ font-weight:bold; margin:6px 0 2px; color:{c['text']}; }}"
        f"h3 {{ color:{c['text']}; margin-bottom:2px; }}"
        f"hr {{ border-color:{c['border']}; }}"
        f"</style></head><body>"
    )

    parts = [head]
    for name, old, new in zip(field_names, old_fields, new_fields):
        if old == new:
            continue
        safe_name = html.escape(name)
        parts.append(f"<h3>{safe_name}</h3>")
        parts.append(f"<p class='label'>Before</p>")
        parts.append(f"<div class='box before'>{old}</div>")
        parts.append(f"<p class='label'>After</p>")
        parts.append(f"<div class='box after'>{new}</div>")
        parts.append("<hr>")
    parts.append("</body></html>")
    return "".join(parts)


def _build_source_diff(old_fields, new_fields, field_names):
    """Build a unified diff string for the Source Diff tab."""
    def pretty(field_html):
        # Make one-liner HTML more readable by adding newlines at block boundaries
        s = field_html
        s = re.sub(r'<br\s*/?><br\s*/?>', '<br><br>\n', s, flags=re.IGNORECASE)
        s = re.sub(r'</div>', '</div>\n', s, flags=re.IGNORECASE)
        return s

    chunks = []
    for name, old, new in zip(field_names, old_fields, new_fields):
        if old == new:
            continue
        old_lines = pretty(old).splitlines(keepends=True)
        new_lines = pretty(new).splitlines(keepends=True)
        chunks.append(f"===== Field: {name} =====\n")
        chunks.extend(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"{name} (before)",
            tofile=f"{name} (after)",
            lineterm="",
        ))
        chunks.append("\n")
    return "".join(chunks)


class PreviewDialog(QDialog):
    def __init__(self, parent, old_fields, new_fields, field_names):
        super().__init__(parent)
        self.setWindowTitle("Preview Formatting Changes")
        self.resize(680, 560)

        layout = QVBoxLayout(self)

        tabs = QTabWidget(self)

        # --- Tab 1: Rendered Preview ---
        colors = _preview_colors(self)
        rendered = QTextBrowser(self)
        rendered.setReadOnly(True)
        rendered.setOpenLinks(False)
        rendered.setHtml(_build_rendered_html(old_fields, new_fields, field_names, colors))
        tabs.addTab(rendered, "Rendered Preview")

        # --- Tab 2: Source Diff ---
        source = QPlainTextEdit(self)
        source.setReadOnly(True)
        source.setPlainText(_build_source_diff(old_fields, new_fields, field_names))
        font = source.font()
        font.setFamily("Courier New")
        source.setFont(font)
        tabs.addTab(source, "Source Diff")

        layout.addWidget(tabs)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Apply Fixes")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)


def on_fix_formatting(editor: Editor) -> None:
    """Action callback when the 'Fix Formatting' button is clicked."""
    def process_and_load():
        note = editor.note
        if not note:
            return
            
        old_fields = [f for f in note.fields]
        new_fields = [fix_formatting(f) for f in note.fields]
        
        if old_fields == new_fields:
            tooltip("No fixable formatting found.")
            return
            
        field_names = [f["name"] for f in note.model()["flds"]]
        
        dialog = PreviewDialog(editor.widget, old_fields, new_fields, field_names)
        if not dialog.exec():
            return
            
        key = _get_note_key(note)
        if key not in _undo_history:
            _undo_history[key] = []
        _undo_history[key].append(old_fields)
        
        for i, val in enumerate(new_fields):
            note.fields[i] = val
            
        editor.loadNote()
        tooltip("Fixed formatting in this note.")

    editor.saveNow(process_and_load)


def undo_last_fix(editor: Editor) -> None:
    """Action callback for 'Undo Fix'."""
    def process_undo():
        note = editor.note
        if not note: return
        
        key = _get_note_key(note)
        if key in _undo_history and _undo_history[key]:
            old_fields = _undo_history[key].pop()
            for i, val in enumerate(old_fields):
                note.fields[i] = val
            editor.loadNote()
            tooltip("Restored previous field values for this note.")
        else:
            tooltip("No previous fix to undo for this note.")
            
    editor.saveNow(process_undo)


def setup_editor_buttons(buttons: list, editor: Editor) -> None:
    """Add buttons to the Anki editor toolbar."""
    btn_fix = editor.addButton(
        icon=None,
        cmd="fix_formatting",
        func=on_fix_formatting,
        tip="Preview and fix Markdown and $ LaTeX formats",
        keys="",
        label="Fix Formatting"
    )
    buttons.append(btn_fix)
    
    btn_undo = editor.addButton(
        icon=None,
        cmd="undo_fix_formatting",
        func=undo_last_fix,
        tip="Undo the last Fix Formatting action for this note",
        keys="",
        label="Undo Fix"
    )
    buttons.append(btn_undo)


gui_hooks.editor_did_init_buttons.append(setup_editor_buttons)

# Removed: automatic paste conversion
# Removed: whole-collection bulk conversion
