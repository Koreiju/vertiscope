"""vertiscope — URL scraping, DOM chunking, and vector retrieval as a CLI tool.

Extracted from the ``web_fiber_haptics`` backend. The pipeline is::

    url ──selenium──> shadow DOM ──tagger──> content xpaths
        ──tree/trie──> patterns ──chunker──> chunks
        ──render──> instances (html_raw + rendered_text)
        ──tf-idf──> incremental index ──> ranked retrieval

Public entry points:

* :func:`vertiscope.pipeline.scrape_url`   — live scan of a URL to instances
* :func:`vertiscope.pipeline.run_pipeline` — the same, from a captured HTML string
* :class:`vertiscope.store.Store`          — SQLite + TF-IDF persistence
* :class:`vertiscope.retrieve.Retriever`   — query -> ranked instances
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
