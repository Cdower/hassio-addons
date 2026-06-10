# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Offline tests for the arXiv metadata provider
# (rootfs/app/calibre-web-automated/cps/metadata_provider/arxiv.py).
#
# These tests are self-contained and require NO network access and NO
# installed Calibre-Web-Automated: the `cps` package and `requests` are
# stubbed, and the arXiv Atom API response is served from an in-file
# fixture. They validate that the provider stays compatible with the
# `cps.services.Metadata` contract shipped by the
# crocodilestick/calibre-web-automated:v4.0.6 base image (Python 3.13).
#
# Run directly:   python3 calibre-web-automated/tests/test_arxiv.py
# Or via pytest:  pytest calibre-web-automated/tests/test_arxiv.py

import importlib.util
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
ARXIV_PATH = os.path.join(
    ADDON_ROOT,
    "rootfs", "app", "calibre-web-automated",
    "cps", "metadata_provider", "arxiv.py",
)

# A trimmed but representative arXiv Atom API response. Exercises: new-style
# id with version suffix, multiple authors, summary, DOI, and categories.
ATOM_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You Need</title>
    <summary>  The dominant sequence transduction models are based on complex
recurrent or convolutional neural networks.  </summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <arxiv:doi>10.48550/arXiv.1706.03762</arxiv:doi>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""


# --------------------------------------------------------------------------
# Test scaffolding: stub the parts of `cps` the provider imports, mirroring
# the real v4.0.6 interface, then load arxiv.py in isolation.
# --------------------------------------------------------------------------
def _build_module():
    import abc
    import dataclasses
    from typing import Dict, Generator, List, Optional, Union

    cps = types.ModuleType("cps")
    logger_mod = types.ModuleType("cps.logger")

    class _Log:
        def warning(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

    logger_mod.create = lambda: _Log()

    constants = types.ModuleType("cps.constants")
    constants.STATIC_DIR = "/static"

    services = types.ModuleType("cps.services")
    metadata = types.ModuleType("cps.services.Metadata")

    @dataclasses.dataclass
    class MetaSourceInfo:
        id: str
        description: str
        link: str

    @dataclasses.dataclass
    class MetaRecord:
        id: Union[str, int]
        title: str
        authors: List[str]
        url: str
        source: MetaSourceInfo
        cover: str = os.path.join(constants.STATIC_DIR, "generic_cover.svg")
        description: Optional[str] = ""
        series: Optional[str] = None
        series_index: Optional[Union[int, float]] = 0
        identifiers: Dict[str, Union[str, int]] = dataclasses.field(default_factory=dict)
        publisher: Optional[str] = None
        publishedDate: Optional[str] = None
        rating: Optional[int] = 0
        languages: Optional[List[str]] = dataclasses.field(default_factory=list)
        tags: Optional[List[str]] = dataclasses.field(default_factory=list)
        format: Optional[str] = None
        confidence_score: Optional[float] = None
        match_reason: Optional[str] = ""

    class Metadata:
        __name__ = "Generic"
        __id__ = "generic"

        def __init__(self):
            self.active = True

        def set_status(self, state):
            self.active = state

        @abc.abstractmethod
        def search(self, query, generic_cover="", locale="en"):
            pass

        @staticmethod
        def get_title_tokens(title, strip_joiners=True):
            # Verbatim from cps/services/Metadata.py @ v4.0.6.
            title_patterns = [
                (re.compile(pat, re.IGNORECASE), repl)
                for pat, repl in [
                    (
                        r"(?i)[({\[](\d{4}|omnibus|anthology|hardcover|"
                        r"audiobook|audio\scd|paperback|turtleback|"
                        r"mass\s*market|edition|ed\.)[\])}]",
                        "",
                    ),
                    (r"(?i)[({\[].*?(edition|ed.).*?[\]})]", ""),
                    (r"(\d+),(\d+)", r"\1\2"),
                    (r"(\s-)", " "),
                    (r"""[:,;!@$%^&*(){}.`~"\s\[\]/]《》「」“”""", " "),
                ]
            ]
            for pat, repl in title_patterns:
                title = pat.sub(repl, title)
            for token in title.split():
                token = token.strip().strip('"').strip("'")
                if token and (
                    not strip_joiners or token.lower() not in ("a", "and", "the", "&")
                ):
                    yield token

    metadata.MetaSourceInfo = MetaSourceInfo
    metadata.MetaRecord = MetaRecord
    metadata.Metadata = Metadata

    # Stub `requests` so the provider imports cleanly and we control responses.
    requests_stub = types.ModuleType("requests")

    class _Resp:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

    requests_stub._Resp = _Resp
    requests_stub.get = lambda *a, **k: _Resp(ATOM_FIXTURE)

    cps.logger = logger_mod
    cps.constants = constants
    cps.services = services
    sys.modules.update({
        "cps": cps,
        "cps.logger": logger_mod,
        "cps.constants": constants,
        "cps.services": services,
        "cps.services.Metadata": metadata,
        "requests": requests_stub,
    })

    spec = importlib.util.spec_from_file_location(
        "cps.metadata_provider.arxiv", ARXIV_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, requests_stub


_ARX, _REQUESTS = _build_module()


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_class_metadata():
    a = _ARX.Arxiv()
    assert a.__name__ == "Arxiv"
    assert a.__id__ == "arxiv"
    assert a.active is True


def test_id_regex_accepts_new_and_old_style():
    rx = _ARX.Arxiv.ID_RE
    for good in ("2301.01234", "2301.01234v3", "arXiv:1706.03762",
                 "hep-th/9901001", "math.GT/0309136v2"):
        assert rx.match(good), good
    for bad in ("attention is all you need", "", "12.34", "foo/bar"):
        assert not rx.match(bad), bad


def test_parse_entry_full_record():
    a = _ARX.Arxiv()
    results = a.search("1706.03762")          # id-lookup branch
    assert len(results) == 1
    m = results[0]
    assert m.title == "Attention Is All You Need"
    assert m.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert m.id == "1706.03762"               # version stripped
    assert m.identifiers == {
        "arxiv": "1706.03762",
        "doi": "10.48550/arXiv.1706.03762",
    }
    assert m.url == "https://arxiv.org/abs/1706.03762"
    assert m.publisher == "arXiv"
    assert m.publishedDate == "2017-06-12"    # YYYY-MM-DD
    assert m.tags == ["cs.CL", "cs.LG"]       # de-duplicated, order preserved
    assert m.source.id == "arxiv"
    assert "dominant sequence transduction" in m.description
    # Summary whitespace must be collapsed.
    assert "  " not in m.description and "\n" not in m.description


def test_default_cover_preserved_when_none_supplied():
    # With no generic_cover argument, MetaRecord's default generic-cover
    # path must be kept rather than blanked to "".
    a = _ARX.Arxiv()
    m = a.search("1706.03762")[0]
    assert m.cover == os.path.join("/static", "generic_cover.svg")


def test_generic_cover_used_when_supplied():
    a = _ARX.Arxiv()
    m = a.search("1706.03762", generic_cover="/covers/fallback.png")[0]
    assert m.cover == "/covers/fallback.png"


def test_entry_without_id_text_is_skipped():
    # An entry whose <id> is empty must not surface a broken match.
    a = _ARX.Arxiv()
    no_id = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id></id><title>Ghost Entry</title></entry>
</feed>"""
    orig = _REQUESTS.get
    _REQUESTS.get = lambda *a, **k: _REQUESTS._Resp(no_id)
    try:
        assert a.search("attention is all you need") == []
    finally:
        _REQUESTS.get = orig


def test_free_text_branch():
    a = _ARX.Arxiv()
    results = a.search("attention is all you need")   # free-text branch
    assert len(results) == 1
    assert results[0].title == "Attention Is All You Need"


def test_empty_and_inactive_short_circuit():
    a = _ARX.Arxiv()
    assert a.search("") == []
    assert a.search("   ") == []
    a.set_status(False)
    assert a.search("1706.03762") == []


def test_network_failure_returns_empty():
    a = _ARX.Arxiv()

    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    orig = _REQUESTS.get
    _REQUESTS.get = boom
    try:
        assert a.search("1706.03762") == []
    finally:
        _REQUESTS.get = orig


def test_malformed_xml_returns_empty():
    a = _ARX.Arxiv()
    orig = _REQUESTS.get
    _REQUESTS.get = lambda *a, **k: _REQUESTS._Resp(b"<not><valid")
    try:
        assert a.search("1706.03762") == []
    finally:
        _REQUESTS.get = orig


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
