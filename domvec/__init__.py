"""domvec — URL scraping, DOM chunking, and vector retrieval as a CLI tool.

Extracted from the ``web_fiber_haptics`` backend. The pipeline is::

    url ──selenium──> shadow DOM ──tagger──> content xpaths
        ──tree/trie──> patterns ──chunker──> chunks
        ──render──> instances (html_raw + rendered_text)
        ──tf-idf──> incremental index ──> ranked retrieval

Public entry points:

* :func:`domvec.pipeline.scrape_url`   — live scan of a URL to instances
* :func:`domvec.pipeline.run_pipeline` — the same, from a captured HTML string
* :class:`domvec.store.Store`          — SQLite + TF-IDF persistence
* :class:`domvec.retrieve.Retriever`   — query -> ranked instances
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
