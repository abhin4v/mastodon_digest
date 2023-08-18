from __future__ import annotations

from mastodon import Mastodon
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from scorers import Scorer

mastodon_client_cache = {}

def enrich_post(post):
    url_parts = urlparse(post['url'])
    api_base_url = f'{url_parts.scheme}://{url_parts.netloc}'
    if api_base_url in mastodon_client_cache:
        m = mastodon_client_cache[api_base_url]
    else:
        m = Mastodon(api_base_url=api_base_url, request_timeout=30)
        mastodon_client_cache[api_base_url] = m
    status = m.status(url_parts.path.split('/')[-1])
    post['replies_count'] = status['replies_count']
    post['reblogs_count'] = status['reblogs_count']
    post['favourites_count'] = status['favourites_count']

class ScoredPost:
    def __init__(self, info: dict):
        self.info = info
        self.score = 0

    @property
    def url(self) -> str:
        return self.info["url"]

    def fetch_metrics(self):
        try:
            enrich_post(self.info)
        except Exception as e:
            print("An error occurred while enriching post: {0} {1}".format(self.url, e))

    def get_home_url(self, mastodon_base_url: str) -> str:
        return f"{mastodon_base_url}/@{self.info['account']['acct']}/{self.info['id']}"

    def get_score(self, scorer: Scorer) -> float:
        self.score = scorer.score(self)
        return self.score

    @property
    def data(self):
        return self.info
