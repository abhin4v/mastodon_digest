from config import Config
from datetime import datetime, timedelta, timezone
from mastodon.return_types import Status
from scorers import Scorer
from typing import Any
from urllib.parse import urlparse
from pathlib import Path
import logging
import requests
import threading

logger = logging.getLogger(__name__)

# requests.Session is not thread-safe; fetch_metrics runs on the
# fetch_metrics thread pool, so give each thread its own session.
_thread_local = threading.local()


def _get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def _load_bad_domains() -> set[str]:
    path = Path(__file__).with_name("bad_domains.txt")
    domains = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.add(line)
    return domains


class ScoredPost:
    bad_domains = _load_bad_domains()

    def __init__(self, data: Status):
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

            url_path_parts = url_parts.path.split("/")
            post_id = url_path_parts[-1]
            if url_path_parts[1] == "objects":
                post_url = _get_session().head(self.url, timeout=30).headers["location"]
                post_id = post_url.split("/")[-1]

            api_url = f"{url_parts.scheme}://{url_parts.netloc}/api/v1/statuses/{post_id}"
            response = _get_session().get(api_url, timeout=30)
            response.raise_for_status()
            status = response.json()
            self._data["replies_count"] = status["replies_count"]
            self._data["reblogs_count"] = status["reblogs_count"]
            self._data["favourites_count"] = status["favourites_count"]
            self._data["account"]["followers_count"] = status["account"]["followers_count"]
            return True
        except Exception as e:
            logger.error("An error occurred while enriching post: %s %s", self.url, e)
            return False

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
