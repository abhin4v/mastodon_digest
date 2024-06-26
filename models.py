from datetime import datetime, timedelta, timezone
from mastodon import Mastodon
from scorers import Scorer
from urllib.parse import urlparse

mastodon_client_cache: dict[str, Mastodon] = {}


def enrich_post(post: dict) -> None:
    url_parts = urlparse(post["url"])
    api_base_url = f"{url_parts.scheme}://{url_parts.netloc}"
    if api_base_url in mastodon_client_cache:
        m = mastodon_client_cache[api_base_url]
    else:
        m = Mastodon(api_base_url=api_base_url, request_timeout=30)
        mastodon_client_cache[api_base_url] = m
    status = m.status(url_parts.path.split("/")[-1])
    post["replies_count"] = status["replies_count"]
    post["reblogs_count"] = status["reblogs_count"]
    post["favourites_count"] = status["favourites_count"]


TAG_BOOST = 1.2
ACCOUNT_BOOST = 1.2


class ScoredPost:
    def __init__(self, data: dict):
        self.data = data
        self.score = 0.0

    def fetch_metrics(self) -> None:
        try:
            enrich_post(self.data)
        except Exception as e:
            print("An error occurred while enriching post: {0} {1}".format(self.data["url"], e))

    def get_home_url(self, mastodon_base_url: str) -> str:
        return f"{mastodon_base_url}/@{self.data['account']['acct']}/{self.data['id']}"

    def calc_score(
        self,
        boosted_tags: set[str],
        boosted_accounts: set[str],
        halflife_hours: int,
        scorer: Scorer,
    ) -> None:
        self.score = scorer.score(self.data)
        tags = [tag.name.lower() for tag in self.data["tags"]]
        if self.score > 0:
            if any((t in boosted_tags) for t in tags):
                self.score = TAG_BOOST * self.score
            if halflife_hours > 0:
                self.score = self.score * (
                    0.5
                    ** (
                        (datetime.now(timezone.utc) - self.data["created_at"])
                        / timedelta(hours=halflife_hours)
                    )
                )
            if self.data["account"]["acct"] in boosted_accounts:
                self.score = ACCOUNT_BOOST * self.score
