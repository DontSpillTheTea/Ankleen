import re
import html

SAFE_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 's', 'del', 'code', 'br', 'div', 'span', 'p', 
    'ul', 'ol', 'li', 'sub', 'sup', 'img', 'a', 'font', 'table', 'tr', 'td', 'th', 'tbody', 'thead', 'style', 'script', 'anki-mathjax', 'hr'
}

def clean_html(text):
    # 1. Specifically repair the trailing tag artifact around backticks
    # Example: `static_cast&lt;type&gt;(expression)<type>`</type> -> `static_cast&lt;type&gt;(expression)`
    # This happens when a browser auto-closes a fake tag after a backtick.
    text = re.sub(r'<([a-zA-Z0-9_]+)>`</\1>', r'`', text)
    
    # 2. Extract and protect code spans
    code_spans = []
    
    def repl_code(m):
        code_content = m.group(1)
        # It might contain HTML tags or entities.
        # We want to unescape everything to raw text, then escape it properly.
        # But wait, what if there are ACTUAL HTML tags inside that we want to keep?
        # Code spans shouldn't have formatted HTML inside, it's literal code.
        # If the browser parsed <type> as a tag, it's in the string as <type>.
        # We unescape it (entities -> chars), then remove any tags?
        # No, if we unescape, &lt; becomes <.
        # Wait, if we use a regex to strip tags, it will strip the <type> we want to keep!
        # So we should unescape to plain text, and then just html.escape the result.
        
        # Unescape all HTML entities
        raw_text = html.unescape(code_content)
        # Re-escape for safe HTML
        escaped_text = html.escape(raw_text)
        
        token = f"__CODE_SPAN_{len(code_spans)}__"
        code_spans.append(f"<code>{escaped_text}</code>")
        return token

    # Match `...`
    text = re.sub(r'`([^`]+?)`', repl_code, text)
    
    # 3. Strip unknown tags (not in SAFE_TAGS)
    def repl_tag(m):
        full_tag = m.group(0)
        tag_name = m.group(1).lower()
        if tag_name in SAFE_TAGS:
            return full_tag
        return "" # Strip the tag
        
    text = re.sub(r'</?([a-zA-Z0-9\-]+)[^>]*>', repl_tag, text)
    
    # 4. Tokenize HTML tags vs text so we only run Markdown on text nodes
    tokens = re.split(r'(<[^>]+>)', text)
    
    _MD_BOLD1 = re.compile(r'\*\*([^*]+?)\*\*')
    _MD_BOLD2 = re.compile(r'(^|[\s\W])__(?![a-zA-Z0-9]+__)([^_]+?)__([\s\W]|$)')
    _MD_STRIKE1 = re.compile(r'~~([^~]+?)~~')
    _MD_STRIKE2 = re.compile(r'(?<!~)~([^~]+?)~(?!=~)')
    
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
    
    # Normalize newlines
    text = re.sub(r'(?:<br\s*/?>|\n|\r)+', '<br><br>', text, flags=re.IGNORECASE)
    text = re.sub(r'^(?:<br\s*/?>)+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:<br\s*/?>)+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>\s*<div>', '</div><br><br><div>', text, flags=re.IGNORECASE)
    
    # 5. Restore code spans
    for i, span_html in enumerate(code_spans):
        text = text.replace(f"__CODE_SPAN_{i}__", span_html)
        
    return text

inputs = [
    "`set.seed()`",
    "`static_cast<type>(expression)`",
    "`static_cast&lt;type&gt;(expression)`",
    "`static_cast&lt;type&gt;(expression)<type>`</type>",
    "Use **bold** and `code`",
    "Already <code>static_cast&lt;int&gt;(x)</code>",
    "What is <b>Type Conversion</b> (Casting)?\n---\nExplicitly converting a value of one type to another.<br><br><div>Style:&nbsp;<div>`static_cast&lt;type&gt;(expression)<type>`</type></div></div>"
]

for inp in inputs:
    print("IN :", inp)
    print("OUT:", clean_html(inp))
    print()
