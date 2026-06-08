# -*- coding: utf-8 -*-
# Calibre-Web Automated metadata provider for arXiv.org
#
# Based on the arXiv plugin for Calibre from the "metadata-sources" project:
#     https://github.com/aroig/metadata-sources
#     Copyright 2012 Abdó Roig-Maranges <abdo.roig@gmail.com>
#
# Rewritten for the Calibre-Web Automated metadata-provider interface
# (cps.services.Metadata) against the arXiv Atom API.
# Copyright 2026 Calibre-Web Automated arXiv provider contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Drop this file into  cps/metadata_provider/  inside the CWA container and
# restart. CWA auto-discovers every .py file in that directory, so no further
# registration is needed. "Arxiv" will then appear in the metadata-search
# provider list in the web UI.
#
# arXiv API docs: https://info.arxiv.org/help/api/user-manual.html

import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests

from cps import logger
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata

log = logger.create()


class Arxiv(Metadata):
    __name__ = "Arxiv"
    __id__ = "arxiv"
    DESCRIPTION = "arXiv.org"
    META_URL = "https://arxiv.org/"
    ABS_URL = "https://arxiv.org/abs/"
    SEARCH_URL = "https://export.arxiv.org/api/query"

    # Atom / arXiv XML namespaces
    NS = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    # New-style id: 2301.01234 or 2301.01234v3
    # Old-style id: math.GT/0309136  or  hep-th/9901001
    ID_RE = re.compile(
        r"^\s*(?:arxiv:)?("
        r"\d{4}\.\d{4,5}(?:v\d+)?"
        r"|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
        r")\s*$",
        re.IGNORECASE,
    )

    MAX_RESULTS = 15

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        if not self.active:
            return []
        query = (query or "").strip()
        if not query:
            return []

        # If the query looks like an arXiv identifier, look it up directly;
        # otherwise do a free-text search across all fields.
        id_match = self.ID_RE.match(query)
        if id_match:
            params = f"id_list={quote(id_match.group(1))}&max_results={self.MAX_RESULTS}"
        else:
            title_tokens = list(self.get_title_tokens(query, strip_joiners=False))
            search_terms = (
                "+".join(quote(t.encode("utf-8")) for t in title_tokens)
                if title_tokens
                else quote(query.encode("utf-8"))
            )
            params = (
                f"search_query=all:{search_terms}"
                f"&start=0&max_results={self.MAX_RESULTS}&sortBy=relevance"
            )

        try:
            resp = requests.get(f"{self.SEARCH_URL}?{params}", timeout=20)
            resp.raise_for_status()
        except Exception as e:
            log.warning("arXiv request failed: %s", e)
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            log.warning("arXiv response parse failed: %s", e)
            return []

        results = []
        for entry in root.findall("atom:entry", self.NS):
            mr = self._parse_entry(entry, generic_cover)
            if mr:
                results.append(mr)
        return results

    def _parse_entry(self, entry, generic_cover: str) -> Optional[MetaRecord]:
        title_el = entry.find("atom:title", self.NS)
        id_el = entry.find("atom:id", self.NS)
        if title_el is None or id_el is None or not (title_el.text or "").strip():
            return None

        # The <id> is a URL like http://arxiv.org/abs/2301.01234v3
        abs_url = (id_el.text or "").strip()
        arxiv_id = abs_url.rsplit("/abs/", 1)[-1] if "/abs/" in abs_url else abs_url
        # Bare id without version, used as the calibre identifier value
        bare_id = re.sub(r"v\d+$", "", arxiv_id)

        title = " ".join((title_el.text or "").split())

        authors = [
            " ".join((name.text or "").split())
            for name in entry.findall("atom:author/atom:name", self.NS)
            if name.text
        ]

        summary_el = entry.find("atom:summary", self.NS)
        description = " ".join((summary_el.text or "").split()) if summary_el is not None else ""

        match = MetaRecord(
            id=bare_id,
            title=title,
            authors=authors,
            url=self.ABS_URL + bare_id,
            source=MetaSourceInfo(
                id=self.__id__,
                description=self.DESCRIPTION,
                link=self.META_URL,
            ),
        )

        match.description = description
        match.cover = generic_cover  # arXiv has no cover art
        match.publisher = "arXiv"
        match.publishedDate = self._parse_date(entry)
        match.tags = self._parse_categories(entry)
        match.identifiers = {"arxiv": bare_id}
        doi = self._find_text(entry, "arxiv:doi")
        if doi:
            match.identifiers["doi"] = doi
        match.series, match.series_index = "", 1
        match.languages = []
        return match

    def _parse_date(self, entry) -> str:
        published = self._find_text(entry, "atom:published")
        if not published:
            return ""
        # Format: 2023-01-03T18:00:00Z  -> keep YYYY-MM-DD
        try:
            return datetime.strptime(published[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    def _parse_categories(self, entry) -> List[str]:
        cats = []
        for cat in entry.findall("atom:category", self.NS):
            term = cat.get("term")
            if term and term not in cats:
                cats.append(term)
        return cats

    def _find_text(self, entry, path) -> str:
        el = entry.find(path, self.NS)
        return (el.text or "").strip() if el is not None and el.text else ""
