from __future__ import annotations

import hashlib
import re
import urllib.parse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from arr.subtitles.base import SubtitleCandidate, SubtitleError
from arr.subtitles.subscene import _extract_srt, _fetch_with, _guess_language


class Addic7edClient:
    """Client for scraping TV show subtitles from Addic7ed."""

    def __init__(self, base_url: str = "https://www.addic7ed.com", session=None):
        self.base = base_url.rstrip("/")
        self._session = session

    def search(
        self,
        *,
        imdb_id: str | None = None,
        tmdb_id: int | None = None,
        title: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        languages: list[str] | None = None,
    ) -> list[SubtitleCandidate]:
        if not title:
            return []

        clean_title = re.sub(r"\s*\(\d{4}\)", "", title).strip()
        wanted_langs = set(languages or ["en"])

        search_url = (
            f"{self.base}/search.php?search={urllib.parse.quote(clean_title)}&Submit=Search"
        )
        try:
            resp = _fetch_with(self._session, search_url)
        except Exception as e:
            raise SubtitleError(f"Addic7ed request failed: {e}") from e

        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"Addic7ed HTTP {getattr(resp, 'status_code', '?')}")

        tree = HTMLParser(resp.text)
        episode_url = None

        if season is not None and episode is not None:
            ep_pattern = re.compile(rf"/serie/[^/]+/{season}/{episode}(?:/|$)", re.IGNORECASE)
            for a in tree.css("a[href*='/serie/']"):
                href = a.attributes.get("href") or ""
                if ep_pattern.search(href):
                    episode_url = href if href.startswith("http") else f"{self.base}{href}"
                    break

        if not episode_url and "/serie/" in getattr(resp, "url", ""):
            episode_url = resp.url

        if not episode_url:
            return []

        try:
            ep_resp = _fetch_with(self._session, episode_url)
        except Exception as e:
            raise SubtitleError(f"Addic7ed episode request failed: {e}") from e

        if getattr(ep_resp, "status_code", 0) != 200:
            raise SubtitleError(f"Addic7ed HTTP {getattr(ep_resp, 'status_code', '?')}")

        ep_tree = HTMLParser(ep_resp.text)
        out: list[SubtitleCandidate] = []
        seen_links: set[str] = set()

        for table in ep_tree.css("table.tabel95"):
            title_node = table.css_first("td.NewsTitle, td.newsTitle")
            header_text = title_node.text().strip() if title_node else ""
            version = "HDTV"
            ver_match = re.search(r"Version\s+([^,]+)", header_text, re.IGNORECASE)
            if ver_match:
                version = ver_match.group(1).strip()

            for row in table.css("tr"):
                dl_node = row.css_first("a[href*='/updated/'], a[href*='/original/']")
                if not dl_node:
                    continue
                href = dl_node.attributes.get("href") or ""
                dl_link = href if href.startswith("http") else f"{self.base}{href}"
                if dl_link in seen_links:
                    continue
                seen_links.add(dl_link)

                lang_node = row.css_first("td.language")
                lang_text = lang_node.text().strip() if lang_node else row.text()
                lang = _guess_language(lang_text)
                if wanted_langs and lang not in wanted_langs:
                    continue

                row_text = row.text().lower()
                hi = (
                    "hearing impaired" in row_text
                    or "hi" in row_text
                    or bool(row.css("img[title*='Hearing']"))
                )

                downloads = 0
                dl_match = re.search(r"(\d+)\s+Downloads", row.text())
                if dl_match:
                    downloads = int(dl_match.group(1))

                tag = (
                    f"S{season:02d}E{episode:02d}"
                    if (season is not None and episode is not None)
                    else ""
                )
                rel_name = f"{clean_title} {tag} {version}".strip()
                rid = int(hashlib.sha1(dl_link.encode()).hexdigest()[:8], 16) % (10**8)

                out.append(
                    SubtitleCandidate(
                        subtitle_id=rid,
                        file_id=rid,
                        language=lang,
                        release_name=rel_name,
                        downloads=downloads,
                        hearing_impaired=hi,
                        hd=True,
                        upload_date="",
                        download_link=dl_link,
                    )
                )

        return out

    def download(self, candidate: SubtitleCandidate) -> bytes:
        if not candidate.download_link:
            raise SubtitleError("No download link")
        try:
            resp = _fetch_with(
                self._session,
                candidate.download_link,
                headers={"Referer": self.base},
            )
        except Exception as e:
            raise SubtitleError(f"Addic7ed download failed: {e}") from e

        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"Addic7ed HTTP {getattr(resp, 'status_code', '?')}")

        return _extract_srt(resp.content)
