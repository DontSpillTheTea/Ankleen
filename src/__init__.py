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
    QPalette,
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


def fix_formatting(html_field: str) -> str:
    """Convert $/$$ delimiters and safely process Markdown and HTML."""
    text = html_field
    
    # --- 1. Math Delimiters ---
    def repl_display(m):
        new_content, is_simple = process_math_content(m.group(1))
        return new_content if is_simple else f'\\[{m.group(1)}\\]'

    def repl_inline(m):
        new_content, is_simple = process_math_content(m.group(1))
        return new_content if is_simple else f'\\({m.group(1)}\\)'

    text = _DISPLAY_MATH.sub(repl_display, text)
    text = _INLINE_MATH.sub(repl_inline, text)
    
    # --- 2. Inline Code & HTML Protection ---
    # Specifically repair trailing unknown tags right after backticks (e.g. <type>`)
    text = re.sub(r'<([a-zA-Z0-9_]+)>`</\1>', r'`', text)
    
    code_spans = []
    
    def repl_code(m):
        raw_text = html.unescape(m.group(1))
        escaped_text = html.escape(raw_text)
        token = f"__CODE_SPAN_{len(code_spans)}__"
        code_spans.append(f"<code>{escaped_text}</code>")
        return token

    # Process all backtick blocks
    text = re.sub(r'`([^`]+?)`', repl_code, text)
    
    # --- 3. Strip Unknown Artifact Tags ---
    def repl_tag(m):
        full_tag = m.group(0)
        tag_name = m.group(1).lower()
        if tag_name in SAFE_TAGS:
            return full_tag
        return ""
        
    text = re.sub(r'</?([a-zA-Z0-9\-]+)[^>]*>', repl_tag, text)
    
    # --- 4. Markdown Processing on Text Nodes Only ---
    tokens = re.split(r'(<[^>]+>)', text)
    for i in range(len(tokens)):
        if tokens[i].startswith('<') and tokens[i].endswith('>'):
            continue # Skip HTML tags
            
        t = tokens[i]
        t = _MD_BOLD1.sub(r'<b>\1</b>', t)
        t = _MD_BOLD2.sub(r'\1<b>\2</b>\3', t)
        t = _MD_STRIKE1.sub(r'<s>\1</s>', t)
        t = _MD_STRIKE2.sub(r'<s>\1</s>', t)
        tokens[i] = t
        
    text = "".join(tokens)
    
    # Normalize spacing to improve readability
    text = re.sub(r'(?:<br\s*/?>|\n|\r)+', '<br><br>', text, flags=re.IGNORECASE)
    text = re.sub(r'^(?:<br\s*/?>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:<br\s*/?>)+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>\s*<div>', '</div><br><br><div>', text, flags=re.IGNORECASE)
    
    # --- 5. Restore Protected Code Spans ---
    for i, span_html in enumerate(code_spans):
        text = text.replace(f"__CODE_SPAN_{i}__", span_html)
    
    return text


# ---------------------------------------------------------------------------
# Editor integration
# ---------------------------------------------------------------------------

_undo_history = {}  # note_key -> list of previous fields

def _get_note_key(note):
    return note.id if note.id else id(note)


def _preview_colors(widget):
    """Extract theme-aware CSS colors from the current Qt palette."""
    pal = widget.palette()
    return {
        "bg":     pal.color(QPalette.ColorRole.Base).name(),
        "alt_bg": pal.color(QPalette.ColorRole.AlternateBase).name(),
        "text":   pal.color(QPalette.ColorRole.Text).name(),
        "border": pal.color(QPalette.ColorRole.Mid).name(),
        "window": pal.color(QPalette.ColorRole.Window).name(),
    }


def _build_rendered_html(old_fields, new_fields, field_names, colors):
    """Build readable before/after HTML for the Rendered Preview tab."""
    bg     = colors["bg"]
    alt_bg = colors["alt_bg"]
    text   = colors["text"]
    border = colors["border"]
    window = colors["window"]

    box_base = (
        f"color:{text}; border:1px solid {border}; border-radius:4px;"
        f"padding:8px; margin-bottom:6px;"
    )
    head = (
        f"<html><head><style>"
        f"body {{ background:{window}; color:{text}; font-family:sans-serif; }}"
        f".before {{ {box_base} background:{bg}; border-left:4px solid {border}; }}"
        f".after  {{ {box_base} background:{alt_bg}; border-left:4px solid {text}; }}"
        f".label  {{ color:{text}; font-weight:bold; margin:4px 0 2px; }}"
        f"</style></head><body>"
    )

    parts = [head]
    for name, old, new in zip(field_names, old_fields, new_fields):
        if old == new:
            continue
        safe_name = html.escape(name)
        parts.append(f"<h3 style='color:{text};margin-bottom:2px'>{safe_name}</h3>")
        parts.append(f"<p class='label'>Before</p>")
        parts.append(f"<div class='before'>{old}</div>")
        parts.append(f"<p class='label'>After</p>")
        parts.append(f"<div class='after'>{new}</div>")
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
