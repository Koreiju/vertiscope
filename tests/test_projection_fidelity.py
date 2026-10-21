"""What survives the two projections, and where it stops surviving.

Capture and projection are different failures. The trie holding a thing is
not the render showing it, and for a long time one number covered both --
`coverage` tested every item against the markdown *and* the raw trie values
concatenated, so anything the markdown dropped still counted as rendered.
These pin the three losses that hid behind that.

No browser: each one is a unit of the rule that was wrong.
"""

from vertiscope import aam
from vertiscope.address import ContentAddress
from vertiscope.markdown import MarkdownLine, _join_labels, _target_of


def _addr(xpath, tag="link", accessor="href|link.anchor/link"):
    return ContentAddress("https://x.test/", xpath, tag, accessor)


class TestNestedLinkTargets:
    """A label deeper than one level still knows where it points."""

    def test_label_nested_below_the_anchor_inherits_its_href(self):
        """claim: a link carries its target in the line, not only the address.

        `<a href><div><span>words</span></div></a>` is the shape every card
        grid uses. The href is keyed by the anchor and the words by the span,
        so the direct lookup missed and the line rendered `[words]` with
        nowhere to go -- while the href unit was separately suppressed as
        "the anchor speaks". The target was not unrendered, it was gone.
        """
        href_at = {"/html/body/a": "https://dest.test/page"}
        owner = "/html/body/a/div/span"
        assert _target_of(owner, href_at) == "https://dest.test/page"

    def test_the_common_shape_still_works(self):
        """`<a href>words</a>` — the case that always worked."""
        href_at = {"/html/body/a": "https://dest.test/"}
        assert _target_of("/html/body/a", href_at) == "https://dest.test/"

    def test_the_nearest_anchor_wins(self):
        """An inner anchor is never overridden by an outer one."""
        href_at = {"/html/body/a": "https://outer.test/",
                   "/html/body/a/div/a": "https://inner.test/"}
        owner = "/html/body/a/div/a/span"
        assert _target_of(owner, href_at) == "https://inner.test/"

    def test_text_with_no_anchor_above_it_gets_no_target(self):
        """Walking up must not invent a target for ordinary prose."""
        href_at = {"/html/body/nav/a": "https://dest.test/"}
        assert _target_of("/html/body/p/span", href_at) == ""


class TestLabelJoinAddressing:
    """A merged label line is filed where the page draws it."""

    def test_joined_line_keeps_the_label_address(self):
        """claim: the visual projection places a unit by its owner's box.

        quotes.toscrape.com writes `<div class=tags>Tags: <meta
        class=keywords content=...>`: the words come from a `display:none`
        meta. Taking the absorbed element's address filed a line the reader
        can see under an element the reader cannot, and the wireframe -- which
        drops units whose owner has no visible box -- lost every one of them.
        """
        label = MarkdownLine(0, "Tags:", _addr("/html/body/div/text()[1]",
                                               tag="text"))
        absorbed = MarkdownLine(0, "change,thinking",
                                _addr("/html/body/div/meta", tag="text"))
        out = _join_labels([label, absorbed])
        assert len(out) == 1
        assert out[0].text == "Tags: change,thinking"
        assert out[0].address.xpath == "/html/body/div/text()[1]", (
            "the merged line is addressed at the element the page hides")


class TestDecorativeMediaIsStillMedia:
    """An empty alt is about announcement, not about existence."""

    def test_img_with_empty_alt_keeps_a_media_render_class(self):
        """claim: every media resource on a page is tracked (§ media scope).

        HTML-AAM makes `<img alt="">` presentational, and that is correct as
        a statement to a screen reader. Used as the *render* class it deleted
        the reference: every illustration on lit.dev carries `alt=""`, and
        the page rendered with none of its images.
        """
        kind, role = aam.kind_of("img", {"alt": "", "src": "/a.svg"})
        assert kind == "image"
        assert role == "none", "the ARIA role must stay what the standard says"

    def test_an_img_with_no_source_is_still_nothing(self):
        """The exemption is for a resource, not for every empty image."""
        kind, _role = aam.kind_of("img", {"alt": ""})
        assert kind == "none"

    def test_timed_media_reads_as_media_not_image(self):
        kind, _role = aam.kind_of("video", {"src": "/v.mp4"})
        assert kind == "media"

    def test_labelled_images_are_unaffected(self):
        kind, role = aam.kind_of("img", {"alt": "a cat", "src": "/c.png"})
        assert kind == "image" and role == "img"
