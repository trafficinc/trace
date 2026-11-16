"""Output adapters consume one immutable dictionary and never query the ORM."""
import base64
from datetime import datetime
from html.parser import HTMLParser
from contextlib import ExitStack
import io
import os
import re
import subprocess  # nosec B404
import sys
import json
import signal
import stat
import tempfile
import zipfile
from django.conf import settings
from django.template import Context, Engine
from django.utils.safestring import mark_safe
from apps.findings.formatting import render_narrative

ACCENTS = {'blue':'245AD1', 'graphite':'4A566B', 'aubergine':'77216F'}
LABELS = {'executive_summary':'Executive summary', 'scope':'Scope', 'objectives':'Objectives', 'methodology':'Methodology',
          'test_summary':'Test summary', 'severity_summary':'Severity summary', 'findings':'Findings', 'evidence':'Evidence references', 'recommendations':'Recommendations'}


class RenderError(Exception):
    pass


def clean_text(text):
    return re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]', '\ufffd', str(text))


def sections(snapshot):
    report, engagement = snapshot['report'], snapshot['engagement']
    rows = []
    for key in report['template']['sections']:
        row = {'key':key, 'title':LABELS[key]}
        if key in {'executive_summary','methodology','recommendations'}:
            row['text'] = report[key]
        elif key in {'scope','objectives'}:
            row['text'] = engagement[key]
        rows.append(row)
    return rows


def html_report(snapshot):
    engine = Engine(dirs=[str(settings.BASE_DIR / 'report_templates')], autoescape=True)
    context = dict(snapshot)
    context['report_sections'] = sections(snapshot)
    for section in context['report_sections']:
        if 'text' in section:
            section['html'] = render_narrative(clean_text(section['text']))
    context['rendered_findings'] = [dict(f, narratives=[{'title':LABELS.get(key,key.replace('_',' ').capitalize()), 'html':render_narrative(clean_text(f[key]))}
        for key in ['description','technical_details','impact','reproduction_steps','remediation','references']]) for f in snapshot['findings']]
    context['accent'] = ACCENTS[snapshot['report']['template']['palette']]
    context['css'] = mark_safe((settings.BASE_DIR / 'static/css/report.css').read_text())  # nosec
    # The source path is fixed operator-owned code. Submitted text is context data.
    return engine.get_template('engagement.html').render(Context(context, use_l10n=False))


class WordNarrative(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.document, self.paragraph, self.bold, self.italic, self.code = document, None, False, False, False
        self.lists, self.link = [], None
    def handle_starttag(self, tag, attrs):
        if tag in {'ul','ol'}:
            self.lists.append('List Number' if tag == 'ol' else 'List Bullet')
        elif tag == 'a':
            self.link = dict(attrs).get('href')
        if tag in {'p','pre','li','h3','h4','h5','h6'}:
            style = (self.lists[-1] if self.lists else 'List Bullet') if tag == 'li' else (f'Heading {int(tag[1])+1}' if tag.startswith('h') else None)
            self.paragraph = self.document.add_paragraph(style=style)
        elif tag == 'br':
            self._paragraph().add_run('\n')
        elif tag == 'strong': self.bold = True
        elif tag == 'em': self.italic = True
        elif tag == 'code': self.code = True
    def handle_endtag(self, tag):
        if tag == 'strong': self.bold = False
        elif tag == 'em': self.italic = False
        elif tag == 'code': self.code = False
        elif tag in {'p','pre','li','h3','h4','h5','h6'}: self.paragraph = None
        elif tag in {'ul','ol'} and self.lists: self.lists.pop()
        elif tag == 'a' and self.link:
            self._paragraph().add_run(clean_text(' ('+self.link+')'))
            self.link = None
    def _paragraph(self):
        if self.paragraph is None: self.paragraph = self.document.add_paragraph()
        return self.paragraph
    def handle_data(self, text):
        run = self._paragraph().add_run(clean_text(text))
        run.bold, run.italic = self.bold, self.italic
        if self.code: run.font.name = 'Courier New'


def docx_report(snapshot):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    document = Document()
    document.styles['Normal'].font.name = 'DejaVu Sans'
    document.styles['Normal'].font.size = Pt(10)
    for name in ['Title','Heading 1','Heading 2','Heading 3']:
        document.styles[name].font.color.rgb = RGBColor.from_string(ACCENTS[snapshot['report']['template']['palette']])
    report, engagement, revision = snapshot['report'], snapshot['engagement'], snapshot['revision']
    def narrative(text): WordNarrative(document).feed(str(render_narrative(clean_text(text))))
    def image(uri, width):
        from PIL import Image
        raw=base64.b64decode(uri.split(',',1)[1], validate=True)
        if len(raw)>2*1024*1024: raise RenderError('Report image size limit exceeded.')
        with Image.open(io.BytesIO(raw),formats=['PNG']) as img:
            w,h=img.size
            if w*h>512*512: raise RenderError('Report image pixel limit exceeded.')
        height=1.0 if width<2 else 3.2
        document.add_picture(io.BytesIO(raw), width=Inches(min(width,height*w/h)))
    section = document.sections[0]
    section.header.paragraphs[0].text = clean_text(' · '.join(filter(None,[report['header'],report['marking']])))
    footer = section.footer.paragraphs[0]
    footer.text = clean_text(' · '.join(filter(None,[report['footer'],report['marking']]))) + '  '
    field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'PAGE'); footer._p.append(field)
    if snapshot.get('logo',{} ) and snapshot['logo'].get('image'): image(snapshot['logo']['image'], 1.4)
    document.add_heading(clean_text(report['title']), 0)
    for value in [engagement['client'], engagement['name'], f"Revision {revision['number']}", revision['generated_at'], report['marking']]:
        if value: document.add_paragraph(clean_text(value))
    document.add_page_break()
    for row in sections(snapshot):
        document.add_heading(row['title'], 1)
        if 'text' in row:
            narrative(row['text'])
            if row['key'] == 'recommendations':
                for f in snapshot['findings']:
                    document.add_heading(clean_text(f['title']), 2); narrative(f['remediation'])
        elif row['key'] == 'severity_summary':
            table = document.add_table(rows=1, cols=2); table.style='Light Shading Accent 1'
            table.rows[0].cells[0].text='Severity'; table.rows[0].cells[1].text='Selected findings'
            for item in snapshot['severity_summary']:
                cells=table.add_row().cells; cells[0].text=item['label']; cells[1].text=str(item['count'])
        elif row['key'] == 'test_summary':
            document.add_paragraph('; '.join(f'{status}: {count}' for status,count in snapshot['test_counts'].items()))
            for case in snapshot['tests']:
                document.add_heading(clean_text(case['title']),2)
                document.add_paragraph(clean_text(case['category']+' · '+case['status']))
                narrative(case['methodology']); narrative(case['actual_result'])
        elif row['key'] == 'findings':
            for f in snapshot['findings']:
                document.add_heading(clean_text(f['title']),2)
                document.add_paragraph(clean_text(f"{f['severity'].capitalize()} · {f['status']} · {f['id']} · Version {f['version']}"))
                if f['cvss_vector']: document.add_paragraph(clean_text('CVSS: '+f['cvss_vector']+' · Score: '+(f['cvss_score'] or 'Not calculated')))
                for key in ['description','technical_details','impact','reproduction_steps','remediation','references']:
                    document.add_heading(key.replace('_',' ').capitalize(),3); narrative(f[key])
                if f['assets']: document.add_paragraph(clean_text('Related assets: '+', '.join(a['name'] for a in f['assets'])))
                if f['test_cases']: document.add_paragraph('Related test cases: '+', '.join(f['test_cases']))
        elif row['key'] == 'evidence':
            for item in snapshot['evidence']:
                document.add_heading(clean_text(item['filename']),2)
                document.add_paragraph(clean_text(f"{item['id']} · {item['kind']} · {item['size']} bytes\nSHA-256: {item['sha256']}"))
                document.add_paragraph(clean_text(item['description']))
                if item.get('image'): image(item['image'],4.8)
    props=document.core_properties
    props.title=clean_text(report['title']); props.author=clean_text(revision['generated_by']); props.revision=revision['number']
    props.created=props.modified=datetime.fromisoformat(revision['generated_at']).replace(tzinfo=None)
    output=io.BytesIO(); document.save(output)
    # Canonical package ordering/timestamps make repeat generation byte-stable.
    result=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as original, zipfile.ZipFile(result,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as normalized:
        for name in sorted(original.namelist()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
            normalized.writestr(info, original.read(name))
    return result.getvalue()


def pdf_report(html):
    env={'PATH':os.defpath, 'PYTHONDONTWRITEBYTECODE':'1'}
    if settings.TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES:
        env['WEASYPRINT_DLL_DIRECTORIES']=settings.TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES
        # dyld uses this for libraries found by CFFI on macOS; operator-controlled only.
        env['DYLD_FALLBACK_LIBRARY_PATH']=settings.TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES
    try:
        result=subprocess.run([sys.executable,'-m','apps.reports.pdf_worker'], input=html.encode(), stdout=subprocess.PIPE,  # nosec B603
            stderr=subprocess.DEVNULL, timeout=settings.TRACE_REPORT_RENDER_TIMEOUT, check=True, cwd=settings.BASE_DIR, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RenderError('PDF rendering failed; check offline dependencies and report limits.') from exc
    if not result.stdout.startswith(b'%PDF-') or len(result.stdout) > settings.TRACE_REPORT_MAX_ARTIFACT_BYTES:
        raise RenderError('PDF output is invalid or too large.')
    return result.stdout


def render_all(snapshot):
    """Bound every adapter, not just PDF, without exposing credentials to workers."""
    from . import storage
    payload = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(payload) > settings.TRACE_REPORT_MAX_SNAPSHOT_BYTES:
        raise RenderError('Report input exceeds the configured snapshot limit.')
    env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'}
    libraries = settings.TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES
    if libraries:
        env.update(WEASYPRINT_DLL_DIRECTORIES=libraries, DYLD_FALLBACK_LIBRARY_PATH=libraries)
    with storage.root_directory():
        pass  # Check owner-only, non-symlink storage before creating private work files.
    with ExitStack() as stack:
        source = stack.enter_context(tempfile.TemporaryFile(dir=storage.root_path()))
        outputs = [stack.enter_context(tempfile.TemporaryFile(dir=storage.root_path())) for _ in range(3)]
        source.write(payload)
        source.seek(0)
        descriptors = [file.fileno() for file in outputs]
        command = [sys.executable, '-m', 'apps.reports.export_worker', json.dumps(descriptors), str(settings.BASE_DIR),
                   str(settings.TRACE_REPORT_MAX_SNAPSHOT_BYTES), str(settings.TRACE_REPORT_MAX_ARTIFACT_BYTES),
                   str(settings.TRACE_REPORT_RENDER_TIMEOUT), libraries]
        process = subprocess.Popen(command, stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # nosec B603
                                   cwd=settings.BASE_DIR, env=env, start_new_session=True, pass_fds=descriptors)
        try:
            status = process.wait(timeout=settings.TRACE_REPORT_RENDER_TIMEOUT)
        except BaseException as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if isinstance(error, subprocess.TimeoutExpired):
                raise RenderError('Report rendering exceeded its time limit.') from None
            raise
        if status != 0:
            raise RenderError('Report rendering failed or exceeded resource limits.')
        results = {}
        for kind, file in zip(['html', 'docx', 'pdf'], outputs):
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > settings.TRACE_REPORT_MAX_ARTIFACT_BYTES:
                raise RenderError('Report output is invalid or too large.')
            file.seek(0)
            data = file.read(settings.TRACE_REPORT_MAX_ARTIFACT_BYTES + 1)
            if not data or len(data) > settings.TRACE_REPORT_MAX_ARTIFACT_BYTES:
                raise RenderError('Report output is invalid or too large.')
            results[kind] = data
        return results
