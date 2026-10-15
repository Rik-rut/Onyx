"""Zero-config Discover endpoints (R4.1/R4.2).

Everything here works without API keys: IMDb charts/search/suggestions and the
TVMaze show index, both cached on disk, with curated fallbacks when a source is
unreachable or bot-blocked.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi import Query as FastQuery

from arr.log import get_logger
from arr.metadata.imdb import ImdbClient, ImdbError
from arr.metadata.tvmaze import TvmazeClient
from arr.web.routes.search import annotate_availability

logger = get_logger("discover")
router = APIRouter(prefix="/api", tags=["discover"])

# Genre chips offered by the Discover UI (R4.1).
DISCOVER_GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Anime",
    "Comedy",
    "Crime",
    "Drama",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
]


def _safe(fn, *args, **kwargs) -> list[dict]:
    """Call a metadata source, degrading to an empty list instead of failing."""
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Discovery source failed: {e}")
        return []
    return result if isinstance(result, list) else []


@router.get("/discover")
async def get_discover(request: Request) -> dict[str, Any]:
    """Trending movies, trending TV, top rated movies and a hero spotlight."""
    cfg = request.app.state.cfg
    imdb = ImdbClient(cfg)
    tvmaze = TvmazeClient(cfg)
    logger.info("Building Discover homepage")
    try:
        trending_movies, top_rated, trending_tv = await asyncio.gather(
            asyncio.to_thread(_safe, imdb.trending_movies, 20),
            asyncio.to_thread(_safe, imdb.top_rated_movies, 20),
            asyncio.to_thread(_safe, tvmaze.trending_tv, 20),
        )
        trending_movies = await asyncio.to_thread(
            annotate_availability, cfg, trending_movies, "movie"
        )
        top_rated = await asyncio.to_thread(annotate_availability, cfg, top_rated, "movie")
        trending_tv = await asyncio.to_thread(annotate_availability, cfg, trending_tv, "tv")

        candidates = trending_movies or top_rated or trending_tv
        spotlight = candidates[0] if candidates else None
        return {
            "spotlight": spotlight,
            "trending_movies": trending_movies,
            "trending_tv": trending_tv,
            "top_rated_movies": top_rated,
            "genres": DISCOVER_GENRES,
        }
    except Exception as e:
        logger.error(f"Discover homepage failed: {e}")
        raise HTTPException(status_code=500, detail=f"Discover unavailable: {e}") from e


@router.get("/discover/genre")
async def get_discover_genre(
    request: Request,
    genre: str = FastQuery(..., min_length=1),
    media_type: str = FastQuery("movie"),
) -> dict[str, Any]:
    """Browse movies or TV shows by genre (zero key required)."""
    cfg = request.app.state.cfg
    kind = "tv" if str(media_type).lower() in ("tv", "show", "series") else "movie"
    logger.info(f"Discover genre browse: {genre} ({kind})")
    try:
        if kind == "tv":
            items = await asyncio.to_thread(_safe, TvmazeClient(cfg).tv_by_genre, genre, 20)
        else:
            items = await asyncio.to_thread(_safe, ImdbClient(cfg).movies_by_genre, genre, 20)
        annotated = await asyncio.to_thread(annotate_availability, cfg, items, kind)
        return {"genre": genre, "media_type": kind, "items": annotated}
    except Exception as e:
        logger.error(f"Genre browse failed for '{genre}': {e}")
        raise HTTPException(status_code=500, detail=f"Genre browse failed: {e}") from e


@router.get("/movie/{imdb_id}/details")
async def get_movie_details(request: Request, imdb_id: str) -> dict[str, Any]:
    """Rich movie details plus "More Like This" suggestions (R4.2)."""
    cfg = request.app.state.cfg
    logger.info(f"Fetching movie details for {imdb_id}")
    try:
        details = await asyncio.to_thread(ImdbClient(cfg).movie_details, imdb_id)
    except ImdbError as e:
        # Scraper blocked: still return a usable (degraded) payload.
        logger.warning(f"IMDb details unavailable for {imdb_id}: {e}")
        details = {
            "id": imdb_id,
            "imdb_id": imdb_id,
            "title": "",
            "year": None,
            "overview": "",
            "rating": None,
            "genres": [],
            "runtime": None,
            "poster": "",
            "stars": [],
            "similar": [],
            "degraded": True,
        }
    except Exception as e:
        logger.error(f"Movie details failed for {imdb_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Movie details failed: {e}") from e

    title = str(details.get("title") or "")
    availability = await asyncio.to_thread(
        annotate_availability,
        cfg,
        [{"title": title, "year": details.get("year"), "id": imdb_id}],
        "movie",
    )
    annotated = availability[0] if availability else {}
    similar = await asyncio.to_thread(
        annotate_availability, cfg, list(details.get("similar") or []), "movie"
    )
    return {
        **details,
        "title": title or details.get("title") or imdb_id,
        "similar": similar,
        "in_library": bool(annotated.get("in_library")),
        "library_status": annotated.get("library_status"),
        "degraded": bool(details.get("degraded")),
    }
