"""What a page body points at: page titles, and the objects its chips name.

The renderer owns the parsing (``apps/wiki/markdown.py``); this is the same
reading turned towards saving — backlinks, and the Dynamic Links a save should
create. Keeping it here means the two never disagree about what a ``[[…]]`` is.
"""

from .markdown import extract_links, extract_references, extract_titles

__all__ = ["extract_links", "extract_references", "extract_titles"]
