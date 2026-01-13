"""Fetchers sub-module"""

from .wikipedia import WikipediaFetcher
from .requests_fetcher import RequestsFetcher, RequestsFetcherWithCookies
from .playwright_fetcher import PlaywrightFetcher, PlaywrightFetcherSync

__all__ = [
    'WikipediaFetcher',
    'RequestsFetcher',
    'RequestsFetcherWithCookies',
    'PlaywrightFetcher',
    'PlaywrightFetcherSync',
]
