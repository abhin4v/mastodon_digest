from config import Config
from datetime import datetime, timedelta, timezone
from mastodon import Mastodon, MastodonVersionError
from scorers import Scorer
from typing import Any, ClassVar
from urllib.parse import urlparse
import requests


class ScoredPost:
    mastodon_client_cache: ClassVar[dict[str, Mastodon]] = {}
    bad_domains = {
        "tech.lgbt",
        "bsd.network",
        "pixelfed.social",
    }

    def __init__(self, data: dict):
        self._data = data
        self.score = 0.0

    def __getattr__(self, name: str) -> Any:
        return self._data[name]

    def set_content(self, content: str) -> None:
        self._data["content"] = content

    def fetch_metrics(self) -> bool:
        if self.visibility == "private":
            return False

        try:
            url_parts = urlparse(self.url)
            if url_parts.netloc in ScoredPost.bad_domains:
                return False

            mastodon_client = self._create_mastodon_client(url_parts)
            if mastodon_client is None:
                return False

            url_path_parts = url_parts.path.split("/")
            post_id = url_path_parts[-1]
            if url_path_parts[1] == "objects":
                post_url = requests.head(self.url).headers["location"]
                post_id = post_url.split("/")[-1]

            status = mastodon_client.status(post_id)
            self._data["replies_count"] = status.replies_count
            self._data["reblogs_count"] = status.reblogs_count
            self._data["favourites_count"] = status.favourites_count
            self._data["account"]["followers_count"] = status.account.followers_count
            return True
        except Exception as e:
            print("An error occurred while enriching post: {0} {1}".format(self.url, e))
            return False

    def _create_mastodon_client(self, url_parts: list[str]) -> Mastodon:
        api_base_url = f"{url_parts.scheme}://{url_parts.netloc}"
        if api_base_url in ScoredPost.mastodon_client_cache:
            return ScoredPost.mastodon_client_cache[api_base_url]
        else:
            mastodon_client = Mastodon(api_base_url=api_base_url, request_timeout=30)
            try:
                mastodon_client.instance()
                ScoredPost.mastodon_client_cache[api_base_url] = mastodon_client
                return mastodon_client
            except MastodonVersionError:
                ScoredPost.bad_domains.add(url_parts.netloc)
                return None

    def get_home_url(self, mastodon_base_url: str) -> str:
        return f"{mastodon_base_url}/@{self.account['acct']}/{self.id}"

    def calc_score(
        self,
        boosted_accounts: set[str],
        config: Config,
        scorer: Scorer,
    ) -> None:
        self.score = scorer.score(self._data)
        tags = [tag.name.lower() for tag in self.tags]
        tag_count_threshold = config.scoring_tag_count_threshold - 1
        if self.score > 0:
            if len(tags) > tag_count_threshold:
                self.score = self.score / ((len(tags) - tag_count_threshold) ** 0.5)
            if any((t in config.digest_boosted_tags) for t in tags):
                self.score = self.score * config.scoring_tag_boost
            if any((t in config.digest_unboosted_tags) for t in tags):
                self.score = self.score / config.scoring_tag_boost
            if self._data['in_reply_to_id'] is not None:
              self.score = self.score / config.scoring_reply_unboost
            if self._data['account']['bot']:
              self.score = self.score / config.scoring_bot_unboost
            if config.scoring_halflife_hours > 0:
                self.score = self.score * (
                    0.5
                    ** (
                        (datetime.now(timezone.utc) - self.created_at)
                        / timedelta(hours=config.scoring_halflife_hours)
                    )
                )
            if self.account.acct in boosted_accounts:
                self.score = config.scoring_account_boost * self.score
