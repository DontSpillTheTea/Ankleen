"""
Gemini LaTeX Fixer for Anki
A non-destructive, one-click editor tool to safely convert $...$ and $$...$$ LaTeX delimiters
and clean up AI-generated Markdown formatting.
"""

import re

from aqt import gui_hooks
from aqt.editor import Editor
from aqt.utils import tooltip
from aqt.qt import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox


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

# Markdown regexes
_MD_CODE = re.compile(r'`([^`<>]+?)`')
_MD_BOLD1 = re.compile(r'\*\*([^*<>]+?)\*\*')
_MD_BOLD2 = re.compile(r'(^|[\s\W])__(?![a-zA-Z0-9]+__)([^_<>]+?)__([\s\W]|$)')
_MD_STRIKE1 = re.compile(r'~~([^~<>]+?)~~')
_MD_STRIKE2 = re.compile(r'(?<!~)~([^~<>]+?)~(?!=~)')


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
    text = text.replace(r'\mid', '|')
    
    # 2. Fractions: \frac{A}{B} -> A / B
    text = re.sub(r'\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}', r'\1 / \2', text)
    
    # 3. Check for remaining LaTeX macros or complex structures
    # If there are backslashes, underscores, carets, or braces left, we consider it complex
    if any(c in text for c in ('\\', '_', '^', '{', '}')):
        return original, False
        
    return text, True


def fix_formatting(html_field: str) -> str:
    """Convert $/$$ delimiters and Markdown formatting."""
    def repl_display(m):
        new_content, is_simple = process_math_content(m.group(1))
        return new_content if is_simple else f'\\[{m.group(1)}\\]'

    def repl_inline(m):
        new_content, is_simple = process_math_content(m.group(1))
        return new_content if is_simple else f'\\({m.group(1)}\\)'

    text = html_field
    text = _DISPLAY_MATH.sub(repl_display, text)
    text = _INLINE_MATH.sub(repl_inline, text)
    
    # Markdown
    text = _MD_CODE.sub(r'<code>\1</code>', text)
    text = _MD_BOLD1.sub(r'<b>\1</b>', text)
    text = _MD_BOLD2.sub(r'\1<b>\2</b>\3', text)
    text = _MD_STRIKE1.sub(r'<s>\1</s>', text)
    text = _MD_STRIKE2.sub(r'<s>\1</s>', text)
    
    # Normalize spacing to improve readability (prevent clumping)
    text = re.sub(r'(?:<br\s*/?>)+', '<br><br>', text, flags=re.IGNORECASE)
    text = re.sub(r'^(?:<br\s*/?>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:<br\s*/?>)+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>\s*<div>', '</div><br><br><div>', text, flags=re.IGNORECASE)
    
    return text


# ---------------------------------------------------------------------------
# Editor integration
# ---------------------------------------------------------------------------

_undo_history = {}  # note_key -> list of previous fields

def _get_note_key(note):
    return note.id if note.id else id(note)


class PreviewDialog(QDialog):
    def __init__(self, parent, old_fields, new_fields, field_names):
        super().__init__(parent)
        self.setWindowTitle("Preview Formatting Changes")
        self.resize(600, 500)
        
        layout = QVBoxLayout(self)
        
        self.text = QTextEdit(self)
        self.text.setReadOnly(True)
        
        html = []
        for name, old, new in zip(field_names, old_fields, new_fields):
            if old != new:
                html.append(f"<h3>Field: {name}</h3>")
                html.append(f"<b>Before:</b><br><div style='background-color: #ffe6e6; padding: 5px; color: black;'>{old}</div>")
                html.append(f"<b>After:</b><br><div style='background-color: #e6ffe6; padding: 5px; color: black;'>{new}</div><hr>")
                
        self.text.setHtml("".join(html))
        layout.addWidget(self.text)
        
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
