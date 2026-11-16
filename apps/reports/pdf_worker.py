"""Fixed, resource-limited offline HTML-to-PDF worker; no submitted template code."""
import base64
import hashlib
import logging
import resource
import sys
logging.disable(logging.CRITICAL)


def offline_fetcher(url):
    prefix='data:image/png;base64,'
    if not url.startswith(prefix) or len(url) > 3 * 1024 * 1024:
        raise ValueError('External resources are disabled.')
    data=base64.b64decode(url[len(prefix):],validate=True)
    if len(data) > 2 * 1024 * 1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid inline PNG.')
    return data


class OfflineFetcher:
    _fail_on_errors = True

    def __call__(self, url):
        from weasyprint.urls import URLFetcherResponse
        return URLFetcherResponse(url, body=offline_fetcher(url), headers={'Content-Type':'image/png'})


def main():
    resource.setrlimit(resource.RLIMIT_CPU,(60,60))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try: resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    except (ValueError,OSError):
        if sys.platform != 'darwin': raise
    sys.stdout.buffer.write(render_pdf(sys.stdin.buffer.read(24 * 1024 * 1024 + 1)))


def render_pdf(html):
    from weasyprint import HTML
    if len(html) > 24 * 1024 * 1024: raise ValueError('Report input limit exceeded.')
    document=HTML(string=html.decode(),url_fetcher=OfflineFetcher()).render()
    if len(document.pages) > 300: raise ValueError('Report page limit exceeded.')
    output=document.write_pdf(pdf_identifier=hashlib.sha256(html).hexdigest().encode())
    if len(output) > 100 * 1024 * 1024: raise ValueError('Report output limit exceeded.')
    return output


if __name__=='__main__':
    try: main()
    except Exception: sys.exit(1)
