"""
Ankleen formatting tests.
Run from the repo root:  python tests.py
Does NOT require Anki to be installed.
"""

import re
import html
import sys

# ---------------------------------------------------------------------------
# Inline copy of fix_formatting logic (no aqt dependency)
# ---------------------------------------------------------------------------

_DISPLAY_MATH = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)
_INLINE_MATH = re.compile(
    r'(?<!\$)(?<!\\)\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\$)'
)
SAFE_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 's', 'del', 'code', 'br', 'div', 'span',
    'p', 'ul', 'ol', 'li', 'sub', 'sup', 'img', 'a', 'font', 'table', 'tr',
    'td', 'th', 'tbody', 'thead', 'style', 'script', 'anki-mathjax', 'hr',
}
_MD_BOLD1   = re.compile(r'\*\*([^*]+?)\*\*')
_MD_BOLD2   = re.compile(r'(^|[\s\W])__(?![a-zA-Z0-9]+__)([^_]+?)__([\s\W]|$)')
_MD_STRIKE1 = re.compile(r'~~([^~]+?)~~')
_MD_STRIKE2 = re.compile(r'(?<!~)~([^~]+?)~(?!=~)')


def process_math_content(content):
    original = content.strip()
    text = original
    text = text.replace(r'\cup', '∪')
    text = text.replace(r'\cap', '∩')
    text = text.replace(r' \mid ', '|')
    text = text.replace(r'\mid', '|')
    text = re.sub(r'\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}', r'\1 / \2', text)
    if any(c in text for c in ('\\', '_', '^', '{', '}')):
        return original, False
    return text, True


def fix_formatting(html_field):
    text = html_field

    def repl_display(m):
        c, ok = process_math_content(m.group(1))
        return c if ok else f'\\[{m.group(1)}\\]'

    def repl_inline(m):
        c, ok = process_math_content(m.group(1))
        return c if ok else f'\\({m.group(1)}\\)'

    text = _DISPLAY_MATH.sub(repl_display, text)
    text = _INLINE_MATH.sub(repl_inline, text)

    # Repair artifact: <tag>`</tag>  ->  `
    text = re.sub(r'<([a-zA-Z0-9_]+)>`</\1>', r'`', text)

    code_spans = []
    def repl_code(m):
        raw  = html.unescape(m.group(1))
        esc  = html.escape(raw)
        tok  = f'__CODE_SPAN_{len(code_spans)}__'
        code_spans.append(f'<code>{esc}</code>')
        return tok
    text = re.sub(r'`([^`]+?)`', repl_code, text)

    def repl_tag(m):
        name = m.group(1).lower()
        return m.group(0) if name in SAFE_TAGS else ''
    text = re.sub(r'</?([a-zA-Z0-9\-]+)[^>]*>', repl_tag, text)

    tokens = re.split(r'(<[^>]+>)', text)
    for i, tok in enumerate(tokens):
        if tok.startswith('<') and tok.endswith('>'):
            continue
        t = _MD_BOLD1.sub(r'<b>\1</b>', tok)
        t = _MD_BOLD2.sub(r'\1<b>\2</b>\3', t)
        t = _MD_STRIKE1.sub(r'<s>\1</s>', t)
        t = _MD_STRIKE2.sub(r'<s>\1</s>', t)
        tokens[i] = t
    text = ''.join(tokens)

    text = re.sub(r'(?:<br\s*/?>|\n|\r)+', '<br><br>', text, flags=re.IGNORECASE)
    text = re.sub(r'^(?:<br\s*/?>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:<br\s*/?>)+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>\s*<div>', '</div><br><br><div>', text, flags=re.IGNORECASE)

    for i, span in enumerate(code_spans):
        text = text.replace(f'__CODE_SPAN_{i}__', span)

    return text


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

PASS = '\033[32mPASS\033[0m'
FAIL = '\033[31mFAIL\033[0m'

cases = [
    # (description, input, expected_output)
    (
        "backtick with plain text",
        "`set.seed()`",
        "<code>set.seed()</code>",
    ),
    (
        "backtick with raw angle brackets",
        "`static_cast<type>(expression)`",
        "<code>static_cast&lt;type&gt;(expression)</code>",
    ),
    (
        "backtick with pre-escaped entities",
        "`static_cast&lt;type&gt;(expression)`",
        "<code>static_cast&lt;type&gt;(expression)</code>",
    ),
    (
        "backtick with trailing artifact tag",
        "`static_cast&lt;type&gt;(expression)<type>`</type>",
        "<code>static_cast&lt;type&gt;(expression)</code>",
    ),
    (
        "bold and inline code together",
        "Use **bold** and `code`",
        "Use <b>bold</b> and <code>code</code>",
    ),
    (
        "already-coded HTML unchanged",
        "Already <code>static_cast&lt;int&gt;(x)</code>",
        "Already <code>static_cast&lt;int&gt;(x)</code>",
    ),
    (
        "math: union",
        r"$P(A \cup B) = P(A) + P(B)$",
        "P(A ∪ B) = P(A) + P(B)",
    ),
    (
        "math: intersection",
        r"$P(A \cap B)$",
        "P(A ∩ B)",
    ),
    (
        "math: mid",
        r"$P(A \mid B)$",
        "P(A|B)",
    ),
    (
        "math: frac",
        r"$P(A|B) = \frac{P(A \cap B)}{P(B)}$",
        "P(A|B) = P(A ∩ B) / P(B)",
    ),
    (
        "math: complex falls back to MathJax",
        r"$A_1^2$",
        r"\(A_1^2\)",
    ),
    (
        "display math: union",
        r"$$P(A \cup B) = P(A) + P(B)$$",
        "P(A ∪ B) = P(A) + P(B)",
    ),
    (
        "full realistic field with artifact",
        "What is <b>Type Conversion</b> (Casting)?\n---\n"
        "Explicitly converting a value of one type to another.<br><br>"
        "<div>Style:&nbsp;<div>"
        "`static_cast&lt;type&gt;(expression)<type>`</type>"
        "</div></div>",
        "What is <b>Type Conversion</b> (Casting)?<br><br>"
        "---<br><br>"
        "Explicitly converting a value of one type to another.<br><br>"
        "<div>Style:&nbsp;<div>"
        "<code>static_cast&lt;type&gt;(expression)</code>"
        "</div></div>",
    ),
]

failures = 0
for desc, inp, expected in cases:
    got = fix_formatting(inp)
    ok  = got == expected
    label = PASS if ok else FAIL
    print(f"[{label}] {desc}")
    if not ok:
        print(f"       INPUT:    {inp!r}")
        print(f"       EXPECTED: {expected!r}")
        print(f"       GOT:      {got!r}")
        failures += 1

print()
if failures:
    print(f"{failures}/{len(cases)} tests FAILED")
    sys.exit(1)
else:
    print(f"All {len(cases)} tests passed.")
