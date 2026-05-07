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
    'td', 'th', 'tbody', 'thead', 'anki-mathjax', 'hr',
    # 'script' and 'style' intentionally excluded
}
_MD_BOLD1   = re.compile(r'\*\*([^*]+?)\*\*')
_MD_BOLD2   = re.compile(r'(^|[\s\W])__(?![a-zA-Z0-9]+__)([^_]+?)__([\s\W]|$)')
_MD_STRIKE1 = re.compile(r'~~([^~]+?)~~')
_MD_STRIKE2 = re.compile(r'(?<!~)~([^~]+?)~(?!=~)')

# Sentinel tokens — private-use Unicode, virtually impossible in real notes
_CODE_PREFIX = "\uE000ANKLEEN_CODE_"
_CODE_SUFFIX = "_\uE001"

def _code_token(i):
    return f"{_CODE_PREFIX}{i}{_CODE_SUFFIX}"

def _repair_code_span_artifacts(code):
    code = re.sub(r'(&lt;([A-Za-z_][A-Za-z0-9_:,. -]*)&gt;)<\2>', r'\1', code)
    code = re.sub(r'(&lt;/([A-Za-z_][A-Za-z0-9_:,. -]*)&gt;)</\2>', r'\1', code)
    return code

_UNKNOWN_TAG_ORPHAN_RE = re.compile(
    r"</(?!(?:" + "|".join(SAFE_TAGS) + r")(?=>))[A-Za-z_][A-Za-z0-9_:.-]*>"
)
_CODE_SPAN_RE = re.compile(r"`([^`\n]+?)`")

def _protect_code_spans(text):
    code_spans = []
    def repl(m):
        code = m.group(1)
        code = _repair_code_span_artifacts(code)
        raw = html.unescape(code)
        esc = html.escape(raw, quote=False)
        tok = _code_token(len(code_spans))
        code_spans.append(f"<code>{esc}</code>")
        return tok
    protected = _CODE_SPAN_RE.sub(repl, text)
    protected = _UNKNOWN_TAG_ORPHAN_RE.sub("", protected)
    return protected, code_spans

def _restore_code_spans(text, code_spans):
    for i, span in enumerate(code_spans):
        text = text.replace(_code_token(i), span)
    return text


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

    # --- 0. Protect inline code FIRST ---
    text = re.sub(r'<([a-zA-Z0-9_]+)>`</\1>', r'`', text)
    text, code_spans = _protect_code_spans(text)

    # --- 1. Math ---
    def repl_display(m):
        c, ok = process_math_content(m.group(1))
        return c if ok else f'\\[{m.group(1)}\\]'
    def repl_inline(m):
        c, ok = process_math_content(m.group(1))
        return c if ok else f'\\({m.group(1)}\\)'
    text = _DISPLAY_MATH.sub(repl_display, text)
    text = _INLINE_MATH.sub(repl_inline, text)

    # --- 2. Strip unknown tags ---
    def repl_tag(m):
        name = m.group(1).lower()
        return m.group(0) if name in SAFE_TAGS else ''
    text = re.sub(r'</?([a-zA-Z0-9\-]+)[^>]*>', repl_tag, text)

    # --- 3. Markdown on text nodes only ---
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

    # --- 4. Normalize spacing ---
    text = re.sub(r'(?:<br\s*/?>|\n|\r)+', '<br><br>', text, flags=re.IGNORECASE)
    text = re.sub(r'^(?:<br\s*/?>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:<br\s*/?>)+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>\s*<div>', '</div><br><br><div>', text, flags=re.IGNORECASE)

    # --- 5. Restore code spans (always last) ---
    text = _restore_code_spans(text, code_spans)
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
        "backtick with raw angle brackets (old case)",
        "`static_cast<type>(expression)`",
        "<code>static_cast&lt;type&gt;(expression)</code>",
    ),
    (
        "backtick with pre-escaped entities (idempotent)",
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
    # --- New C++ template tests ---
    (
        "C++: static_cast<double> in code span",
        "Fix: Cast one to double: `static_cast<double>(count) / total`.",
        "Fix: Cast one to double: <code>static_cast&lt;double&gt;(count) / total</code>.",
    ),
    (
        "C++: vector<int> in code span",
        "Use `vector<int>` here.",
        "Use <code>vector&lt;int&gt;</code> here.",
    ),
    (
        "C++: comparison operators (& becomes &amp;, < becomes &lt;, > stays >)",
        "Use `x < y && y > z`.",
        "Use <code>x &lt; y &amp;&amp; y &gt; z</code>.",
    ),
    (
        "C++: pre-escaped entities idempotent",
        "Use `static_cast&lt;double&gt;(count)`.",
        "Use <code>static_cast&lt;double&gt;(count)</code>.",
    ),
    (
        "C++: already wrapped in <code> is untouched",
        "Already <code>static_cast&lt;double&gt;(count)</code>.",
        "Already <code>static_cast&lt;double&gt;(count)</code>.",
    ),
    # --- Browser HTML artifact tests ---
    (
        "browser artifact: duplicated fake tag inside code span",
        "<b>Fix:</b> Cast one to double: `static_cast&lt;double&gt;<double>(count) / total`.</double>",
        "<b>Fix:</b> Cast one to double: <code>static_cast&lt;double&gt;(count) / total</code>.",
    ),
    (
        "browser artifact: vector<int> orphan tag",
        "Use `vector&lt;int&gt;<int>`.</int>",
        "Use <code>vector&lt;int&gt;</code>.",
    ),
    (
        "browser artifact: std::map with orphan tag (space in type name prevents dedup, orphan still stripped)",
        "Use `std::map&lt;string, int&gt;<string>(x)`.</string>",
        "Use <code>std::map&lt;string, int&gt;&lt;string&gt;(x)</code>.",
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
