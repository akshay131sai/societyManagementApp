#!/usr/bin/env python
"""Wrap index.html into a standalone document at dist/index.html.

index.html is authored as Artifact body content — the publisher supplies the
<!doctype>, <head> and <body> itself. For hosting the page anywhere else
(localhost, Netlify, an nginx box) it needs those tags, so this emits a real
document without duplicating the source.

    python build.py            # writes dist/index.html
    python build.py --serve    # writes it, then serves dist/ on :4173
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "index.html")
OUT_DIR = os.path.join(HERE, "dist")
OUT = os.path.join(OUT_DIR, "index.html")

DESCRIPTION = (
    "NestFlow — society and apartment management for India. Maintenance "
    "billing, utilities, visitors, complaints and housekeeping, one app per "
    "society."
)


def build():
    body = io.open(SRC, encoding="utf-8").read()

    title_match = re.search(r"<title>(.*?)</title>", body, re.S)
    title = title_match.group(1).strip() if title_match else "NestFlow"

    # The <title> and the font <link>s belong in <head>, not <body>.
    head_bits = []
    for pattern in (r"<title>.*?</title>\s*", r"<link\b[^>]*>\s*"):
        for m in re.findall(pattern, body, re.S):
            head_bits.append(m.strip())
        body = re.sub(pattern, "", body, flags=re.S)

    doc = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="description" content="%s">\n'
        '<meta property="og:title" content="%s">\n'
        '<meta property="og:description" content="%s">\n'
        '<meta property="og:type" content="website">\n'
        '<link rel="icon" href="data:image/svg+xml,'
        "%%3Csvg xmlns=%%27http://www.w3.org/2000/svg%%27 viewBox=%%270 0 100 100%%27"
        "%%3E%%3Ctext y=%%27.9em%%27 font-size=%%2790%%27%%3E%%F0%%9F%%8F%%98%%3C/text%%3E%%3C/svg%%3E\">\n"
        "%s\n"
        "<style>*,*::before,*::after{box-sizing:border-box}"
        "html{-webkit-text-size-adjust:100%%}body{margin:0}</style>\n"
        "</head>\n"
        "<body>\n"
        "%s\n"
        "</body>\n"
        "</html>\n"
    ) % (DESCRIPTION, title, DESCRIPTION, "\n".join(head_bits), body.strip())

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    io.open(OUT, "w", encoding="utf-8").write(doc)
    print("Built %s (%d KB)" % (OUT, len(doc.encode("utf-8")) // 1024))


def serve(port=4173):
    os.chdir(OUT_DIR)
    try:
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    except ImportError:
        from SimpleHTTPServer import SimpleHTTPRequestHandler
        from BaseHTTPServer import HTTPServer as ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    print("Serving http://localhost:%d/  (Ctrl+C to stop)" % port)
    sys.stdout.flush()
    ThreadingHTTPServer(("127.0.0.1", port), Quiet).serve_forever()


if __name__ == "__main__":
    build()
    if "--serve" in sys.argv:
        serve()
