"""Small, escape-first narrative format. No submitted HTML is trusted or retained as HTML."""
import re
from django.utils.html import escape
from django.utils.safestring import mark_safe


# Delimiters inside a link label cannot reopen the search at each '['. Matching
# unformatted input also keeps generated tags out of href attributes entirely.
INLINE = re.compile(
    r"`([^`\n]+)`|\*\*([^*\n]+)\*\*|(?<!\*)\*([^*\n]+)\*(?!\*)"
    r'|\[([^\[\]\n]{1,2000})\]\((https?://[^\s<>"\)\n]{1,2048})\)'
)


def _inline(text: str, *, links: bool = True) -> str:
    from urllib.parse import urlsplit
    output: list[str] = []
    previous = 0
    for match in INLINE.finditer(text):
        output.append(str(escape(text[previous:match.start()])))
        code, strong, emphasis, label, url = match.groups()
        if code is not None:
            output.append('<code>' + str(escape(code)) + '</code>')
        elif strong is not None:
            output.append('<strong>' + str(escape(strong)) + '</strong>')
        elif emphasis is not None:
            output.append('<em>' + str(escape(emphasis)) + '</em>')
        else:
            try:
                parsed = urlsplit(url)
                valid = links and parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                parsed.port  # Reject malformed port syntax too.
            except ValueError:
                valid = False
            if valid:
                output.append('<a href="' + str(escape(url)) + '" rel="noopener noreferrer">' + _inline(label, links=False) + '</a>')
            else:
                output.append(str(escape(match[0])))
        previous = match.end()
    output.append(str(escape(text[previous:])))
    return ''.join(output)


def render_narrative(value):
    inline = _inline
    output: list[str] = []
    paragraph: list[str] = []
    code: list[str] | None = None
    list_tag = None
    def close_list():
        nonlocal list_tag
        if list_tag:
            output.append(f"</{list_tag}>")
            list_tag = None
    def flush():
        if paragraph:
            output.append('<p>' + '<br>'.join(paragraph) + '</p>')
            paragraph.clear()
    for line in str(value or '').splitlines():
        match_list = re.match(r'^(?:([-*]) |(\d+)\. )(.*)$', line)
        if code is None and not match_list:
            close_list()
        if line.startswith('```'):
            flush()
            if code is None:
                code = []
            else:
                output.append('<pre><code>' + str(escape('\n'.join(code))) + '</code></pre>')
                code = None
        elif code is not None:
            code.append(line)
        elif not line.strip():
            flush()
        elif match := re.match(r'^(#{1,4}) (.*)$', line):
            flush()
            level = len(match[1]) + 2
            output.append(f'<h{level}>' + inline(match[2]) + f'</h{level}>')
        elif match_list:
            flush()
            tag = 'ol' if match_list[2] else 'ul'
            if tag != list_tag:
                close_list()
                output.append(f'<{tag}>')
                list_tag = tag
            output.append('<li>' + inline(match_list[3]) + '</li>')
        else:
            paragraph.append(inline(line))
    flush()
    close_list()
    if code is not None:
        output.append('<pre><code>' + str(escape('\n'.join(code))) + '</code></pre>')
    # Only fixed tags and escaped text can reach this boundary.
    return mark_safe(''.join(output))  # nosec
