import re
from functools import lru_cache

_INDEX_PATTERN = re.compile(r'\[\d+\]')


@lru_cache(maxsize=32768)
def generalize_xpath(absolute_xpath: str) -> str:
    """Strip array indices from an xpath to get the structural pattern.

    '/html/body/div[2]/ul/li[5]/a' -> '/html/body/div/ul/li/a'

    Cached because the chunker and renderer call this for every tag and
    every descendant of every instance — the same xpath typically recurs
    dozens of times per page, and the regex pass dominated profiling.
    """
    return _INDEX_PATTERN.sub('', absolute_xpath)

def is_match(general_xpath: str, test_xpath: str) -> bool:
    """
    Checks if a test_xpath matches the given general_xpath structure.
    """
    return generalize_xpath(test_xpath) == general_xpath

def get_parent_xpath(xpath: str) -> str:
    """
    Returns the XPath of the parent node.
    Example: '/html/body/div[2]/span' -> '/html/body/div[2]'
    """
    if not xpath or xpath == "/":
        return "/"
    
    parts = xpath.rstrip("/").split("/")
    if len(parts) <= 2:
        return "/"
    
    return "/".join(parts[:-1])
