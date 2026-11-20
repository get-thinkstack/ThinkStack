"""HTTP layer: one router per feature, mounted under /api/<prefix> in main.py.

Routes validate input, call domain/ and infrastructure/, and shape the
response; the logic lives in domain/. Every handler is reachable from the
webview, so path and filename arguments are untrusted input.
"""
