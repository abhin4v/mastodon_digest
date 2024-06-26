from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from mastodon import Mastodon
from scorers import Scorer
from urllib.parse import urlparse

TAG_BOOST = 1.2
ACCOUNT_BOOST = 1.2


class ScoredPost:
    mastodon_client_cache: ClassVar[dict[str, Mastodon]] = {}

    def __init__(self, data: dict):
        self._data = data
        self.score = 0.0

    def __getattr__(self, name: str) -> Any:
        return self._data[name]

    def set_content(self, content: str) -> None:
        self._data["content"] = content

    def fetch_metrics(self) -> None:
        try:
            url_parts = urlparse(self.url)
            api_base_url = f"{url_parts.scheme}://{url_parts.netloc}"
            if api_base_url in ScoredPost.mastodon_client_cache:
                m = ScoredPost.mastodon_client_cache[api_base_url]
            else:
                m = Mastodon(api_base_url=api_base_url, request_timeout=30)
                ScoredPost.mastodon_client_cache[api_base_url] = m
            status = m.status(url_parts.path.split("/")[-1])
            self._data["replies_count"] = status["replies_count"]
            self._data["reblogs_count"] = status["reblogs_count"]
            self._data["favourites_count"] = status["favourites_count"]
        except Exception as e:
            print("An error occurred while enriching post: {0} {1}".format(self.url, e))

    def get_home_url(self, mastodon_base_url: str) -> str:
        return f"{mastodon_base_url}/@{self.account['acct']}/{self.id}"

    def calc_score(
        self,
        boosted_tags: set[str],
        boosted_accounts: set[str],
        halflife_hours: int,
        scorer: Scorer,
    ) -> None:
        self.score = scorer.score(self._data)
        tags = [tag.name.lower() for tag in self.tags]
        if self.score > 0:
            if any((t in boosted_tags) for t in tags):
                self.score = TAG_BOOST * self.score
            if halflife_hours > 0:
                self.score = self.score * (
                    0.5
                    ** (
                        (datetime.now(timezone.utc) - self.created_at)
                        / timedelta(hours=halflife_hours)
                    )
                )
            if self.account["acct"] in boosted_accounts:
                self.score = ACCOUNT_BOOST * self.score
