"""The browser's governing artifact (PLUGIN_GOAL 142, ruling T-10).

Every capability of a browser instance, one typed method each. The plugin
reads this file: each public method becomes a field of the browser's
markdown control panel (`domvec/browser.md`), with the type deciding how the
field acts -- no argument: an action (click), bool: a toggle, Literal: a
choice stepped in place, str: typed text. Add a method here and the panel
grows a field; the instance (its cockpit note) is linked to this class in
the computation graph.
"""
from typing import Literal


class Browser:
    def url(self, to: str = "") -> None: ...          # go there; navigation writes it back
    def back(self) -> None: ...                         # one page back
    def forward(self) -> None: ...                      # one page forward
    def scan(self) -> None: ...                         # scan the page now
    def live(self, on: bool = True) -> None: ...        # stream the page into the store
    def boxes(self, on: bool = False) -> None: ...      # show the chunk outlines
    def scope(self, rung: Literal["chunk", "page", "live"] = "live") -> None: ...  # the scope ladder
