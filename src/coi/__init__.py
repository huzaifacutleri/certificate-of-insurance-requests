"""COI Assistant: turns certificate-of-insurance request emails into reviewed drafts.

Pipeline (see docs/ARCHITECTURE.md):

    raw email -> ingest -> extract -> match client -> validate -> draft -> human review -> PDF

The package is deliberately split into small modules with no web-framework
dependency in the core, so every step can be unit-tested offline.
"""

__version__ = "0.1.0"
