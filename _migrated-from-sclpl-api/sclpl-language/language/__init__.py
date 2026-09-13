"""Editor-neutral SCLPLL language intelligence.

Nothing in this package executes a workflow.  It adapts the canonical lexer, parser,
IR, formatter, registries, and static plugin manifests for editors and other tools.
"""

from sclpl.language.analysis import DocumentAnalysis, analyze, format_sclpll

__all__ = ["DocumentAnalysis", "analyze", "format_sclpll"]
