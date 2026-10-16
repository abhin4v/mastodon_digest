from collections import defaultdict
from bs4 import BeautifulSoup
from config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from mastodon import Mastodon
from mastodon.return_types import Status
from mastodon.types_base import PaginatableList
from models import ScoredPost
from threading import Lock
from typing import Optional
from urllib.parse import urlparse
import itertools
import logging
import re
import requests

logger = logging.getLogger(__name__)

METRICS_MAX_WORKERS = 10


class PostFilterator:
    def __init__(
        self,
        digested_post_urls: set[str],
        mastodon_client: Mastodon,
        config: Config,
    ) -> None:
        self._seen_post_urls: set[str] = set()
        self._mastodon_client = mastodon_client
        self._config = config
        self._stats: defaultdict[str, int] = defaultdict(int)
        self._mastodon_user = mastodon_client.me()
        self._server_filters = self._get_server_filter_as_regex()
        self._trending_post_ids = self._get_trending_post_ids()
        self._digested_post_urls = digested_post_urls
        self._min_post_created_at = datetime.now(timezone.utc) - timedelta(
            hours=config.post_max_age_hours
        )
        self._contents: set[str] = set()

        logger.info("Fetching data for %s", self._mastodon_user.username)

    def _get_server_filter_as_regex(self) -> Optional[re.Pattern[str]]:
        filters = self._mastodon_client.filters()
        if filters:
            filter_strings = []
            for keyword_filter in filters:
                if not keyword_filter["irreversible"]:
                    continue

                if not "home" in keyword_filter["context"]:
                    continue

                filter_string = re.escape(keyword_filter["phrase"])
                if keyword_filter["whole_word"]:
                    filter_string = "\\b" + filter_string + "\\b"
                filter_strings.append(filter_string)
            return re.compile("|".join(filter_strings), flags=re.IGNORECASE)
        return None

    def _get_trending_post_ids(self) -> set[int]:
        if self._config.timeline_exclude_trending:
            return set(p.id for p in self._mastodon_client.trending_statuses())
        return set()

    def _is_short_post(self, post: Status, soup: BeautifulSoup) -> bool:
        words = [
            word
            for word in soup.text.split()
            if not (word.startswith("#") or word.startswith("@") or word.startswith("http"))
        ]

        return (len(words) == 0) or (
            len(words) <= self._config.post_min_word_count
            and len(post.media_attachments) == 0
            and post.poll is None
            and len(
                soup.find_all(
                    lambda tag: tag.name == "a" and "mention" not in tag.attrs.get("class", [])
                )
            )
            == 0
        )

    def _is_valid_lang_post(self, post: Status) -> bool:
        if len(self._config.post_languages) > 0:
            return post.language is None or post.language in self._config.post_languages
        return True

    def _is_interacted_post(self, post: Status) -> bool:
        return (
            post.reblogged
            or post.favourited
            or post.bookmarked
            or post.account.id == self._mastodon_user.id
            or post.in_reply_to_account_id == self._mastodon_user.id
        )

    def add_seen_post_url(self, url: str) -> None:
        self._seen_post_urls.add(url)

    def filter_posts(self, posts: list[Status]) -> tuple[list[Status], set[str | None]]:
        filtered_posts = []
        boost_posts_urls = set()
        for post in posts:
            boost = False
            if post.reblog is not None:
                post = post.reblog  # look at the boosted post
                boost = True

            if post.url in self._seen_post_urls:
                logger.debug("Excluded seen post %s", post.url)
                continue

            if (
                self._config.timeline_exclude_previously_digested_posts
                and post.url in self._digested_post_urls
            ):
                logger.debug("Excluded digested post %s", post.url)
                self._stats["digested_post_count"] += 1
                continue

            if post.visibility == "direct":
                logger.debug("Excluded direct post %s", post.url)
                self._stats["direct_post_count"] += 1
                continue

            if post.muted:
                logger.debug("Excluded muted post %s", post.url)
                self._stats["muted_post_count"] += 1
                continue

            if self._is_interacted_post(post):
                logger.debug("Excluded interacted post %s", post.url)
                self._stats["interacted_post_count"] += 1
                continue

            if post.created_at < self._min_post_created_at:
                logger.debug("Excluded old post %s", post.url)
                self._stats["old_post_count"] += 1
                continue

            if self._config.timeline_exclude_trending and post.id in self._trending_post_ids:
                logger.debug("Excluded trending post %s", post.url)
                self._stats["trending_post_count"] += 1
                continue

            if post.content in self._contents:
                logger.debug("Excluded duplicate post %s", post.url)
                self._stats["duplicate_post_count"] += 1
                continue

            if not self._is_valid_lang_post(post):
                logger.debug("Excluded foreign language post %s", post.url)
                self._stats["foreign_language_post_count"] += 1
                continue

            soup = BeautifulSoup(post.content, "html.parser")
            if self._is_short_post(post, soup):
                logger.debug("Excluded short post %s", post.url)
                self._stats["short_post_count"] += 1
                continue

            if any(
                "home" in f.filter.context and f.filter.filter_action == "hide"
                for f in (post.filtered or [])
            ):
                logger.debug(
                    "Excluded post matching user's filters on server side %s", post.url
                )
                self._stats["filtered_post_count"] += 1
                continue

            content_text = soup.get_text(" ", strip=True)
            server_filters = self._server_filters
            if server_filters is not None:
                if (
                    server_filters.search(content_text) is not None
                    or server_filters.search(post.spoiler_text) is not None
                    or any(
                        media.description is not None
                        and server_filters.search(media.description) is not None
                        for media in post.media_attachments
                    )
                ):
                    logger.debug(
                        "Excluded post matching user's filters on client side %s", post.url
                    )
                    self._stats["filtered_post_count"] += 1
                    continue

            filtered_posts.append(post)
            if boost:
                boost_posts_urls.add(post.url)

        return (filtered_posts, boost_posts_urls)

    def print_stats(self):
        logger.info("Excluded %s posts:", sum(self._stats.values()))
        for key, val in self._stats.items():
            logger.info("    %s = %s", key, val)


def fetch_metrics(all_posts: list[ScoredPost]) -> None:
    """Fetches API metrics for all posts, one worker thread per instance

    Posts are grouped by instance (URL netloc) and each group is fetched
    sequentially by a single thread, so no instance receives concurrent
    requests, while different instances are fetched in parallel. The largest
    group is split in half and fetched by two threads, since it dominates
    the total time.
    """
    total_count = len(all_posts)
    logger.info("Fetching metrics for %s posts...", total_count)
    if not all_posts:
        return

    groups: dict[str, list[ScoredPost]] = {}
    for post in all_posts:
        try:
            netloc = urlparse(post.url).netloc
        except Exception:
            netloc = ""
        groups.setdefault(netloc, []).append(post)

    tasks: list[list[ScoredPost]] = []
    sorted_groups = sorted(groups.values(), key=len, reverse=True)
    for i, group in enumerate(sorted_groups):
        if i == 0 and len(group) >= 2:
            mid = len(group) // 2
            tasks.extend([group[:mid], group[mid:]])
        else:
            tasks.append(group)

    progress_lock = Lock()
    attempt_counter = itertools.count(1)

    def fetch_group(group: list[ScoredPost]) -> None:
        for post in group:
            fetched = post.fetch_metrics()
            with progress_lock:
                i = next(attempt_counter)
                if fetched:
                    logger.info("[%s/%s] Fetched metrics for %s", i, total_count, post.url)

    executor = ThreadPoolExecutor(max_workers=METRICS_MAX_WORKERS)
    try:
        futures = [executor.submit(fetch_group, group) for group in tasks]
        for future in as_completed(futures):
            future.result()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def fetch_posts_and_boosts(
    digested_post_urls: set[str], mastodon_client: Mastodon, config: Config
) -> tuple[list[ScoredPost], list[ScoredPost]]:
    """Fetches posts form the home timeline that the account hasn't interacted with"""
    start = datetime.now(timezone.utc) - timedelta(hours=config.timeline_hours_limit)
    posts: list[ScoredPost] = []
    boosts: list[ScoredPost] = []
    total_posts_seen = 0
    filterator = PostFilterator(digested_post_urls, mastodon_client, config)

    # Iterate over our home timeline until we run out of posts or we hit the limit
    response: Optional[PaginatableList[Status]] = mastodon_client.timeline(
        min_id=start, limit=40
    )
    while response and total_posts_seen < config.timeline_posts_limit:
        logger.info("Fetched timeline posts")
        resp_posts, boost_posts_urls = filterator.filter_posts(response)

        for post in resp_posts:
            scored_post = ScoredPost(post)  # wrap the post data as a ScoredPost
            total_posts_seen += 1
            # Append to either the boosts list or the posts lists
            if post.url in boost_posts_urls:
                boosts.append(scored_post)
            else:
                posts.append(scored_post)
            filterator.add_seen_post_url(scored_post.url)

        # fetch the previous (because of reverse chron) page of results
        response = mastodon_client.fetch_previous(response)  # type: ignore[arg-type]

    filterator.print_stats()

    fetch_metrics(list(itertools.chain(posts, boosts)))

    return posts, boosts


def fetch_boosted_accounts(mastodon_client: Mastodon, boosted_lists: set[int]) -> set[str]:
    logger.info("Fetching accounts for %s boosted lists...", len(boosted_lists))
    boosted_accounts: list[str] = []
    for id in boosted_lists:
        accounts = mastodon_client.list_accounts(id, limit="0")
        boosted_accounts.extend(account.acct for account in accounts)

    return set(boosted_accounts)


def get_known_instance_domains() -> set[str]:
    logger.info("Fetching known instance domains...")
    try:
        with requests.get("https://nodes.fediverse.party/nodes.json", timeout=30) as resp:
            domains = resp.json()
            assert type(domains) == list
            known_domains = set("://" + domain + "/" for domain in domains)
            logger.info("Known instance domains: %s", len(known_domains))
            return known_domains
    except requests.exceptions.RequestException as err:
        logger.warning("Error in getting fediverse nodes.json: %s", err)
        return set()
