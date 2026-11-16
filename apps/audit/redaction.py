"""Fail-closed field selection plus conservative credential redaction in business text."""
import re

REDACTED='[REDACTED]'
# Deliberately redact the remainder of a credential-bearing line, including spaces.
LABEL=re.compile(r'''(?im)(["']?(?:password|passwd|pwd|secret|client[_ -]?secret|api[_ -]?key|access[_ -]?key|secret[_ -]?key|private[_ -]?key|access[_ -]?token|refresh[_ -]?token|id[_ -]?token|token|session(?:id|[_ -]?token|[_ -]?key)?|csrf(?:middlewaretoken|[_ -]?token)?|authorization|proxy-authorization|cookie|set-cookie)["']?\s*[:=]\s*)[^\r\n]*''')
PEM=re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)')
TOKEN=re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|glpat-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16}|ASIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?:pbkdf2_sha256|scrypt|argon2)\$[^\s]+)')
USERINFO=re.compile(r'(?<![a-zA-Z0-9+.\-])([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@]+:[^\s/@]+@')
BEARER=re.compile(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/=_\-.]+')


def redact_text(value):
    value=PEM.sub(REDACTED,str(value))
    value=USERINFO.sub(r'\1'+REDACTED+'@',value)
    value=TOKEN.sub(REDACTED,value)
    value=BEARER.sub(lambda m:m[1]+' '+REDACTED,value)
    return LABEL.sub(lambda m:m[1]+REDACTED,value)


def redact_value(value):
    if isinstance(value,str): return redact_text(value)
    if isinstance(value,list): return [redact_value(item) for item in value]
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if re.search(r'password|passwd|secret|token|cookie|authorization|session|hash|storage_key',str(key),re.I):
                continue
            result[str(key)]=redact_value(item)
        return result
    if value is None or isinstance(value,(bool,int,float)): return value
    return redact_text(str(value))
