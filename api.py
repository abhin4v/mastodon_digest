from bs4 import BeautifulSoup
from config import Config
from datetime import datetime, timedelta, timezone
from mastodon import Mastodon
from models import ScoredPost
from typing import Optional
import itertools
import re
import requests


class PostFilterator:
    def __init__(
        self,
        digested_post_urls: set[str],
        mastodon_client: Mastodon,
        config: Config,
    ) -> None:
        self._seen_post_urls = set()
        self._mastodon_client = mastodon_client
        self._config = config
        self._direct_post_count = 0
        self._muted_post_count = 0
        self._interacted_post_count = 0
        self._old_post_count = 0
        self._trending_post_count = 0
        self._digested_post_count = 0
        self._duplicate_post_count = 0
        self._foreign_language_post_count = 0
        self._filtered_post_count = 0
        self._short_post_count = 0
        self._mastodon_user = mastodon_client.me()
        self._server_filters = self._get_server_filter_as_regex()
        self._trending_post_ids = self._get_trending_post_ids()
        self._digested_post_urls = digested_post_urls
        self._min_post_created_at = datetime.now(timezone.utc) - timedelta(
            hours=config.post_max_age_hours
        )
        self._contents = set()

        print(f"Fetching data for {self._mastodon_user.username}")

    def _get_server_filter_as_regex(self) -> Optional[re.Pattern[str]]:
        filters = self._mastodon_client.filters()
        if filters:
            filter_strings = []
            for keyword_filter in filters:
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

    def _is_short_post(self, post: dict, soup: BeautifulSoup) -> bool:
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

    def _is_valid_lang_post(self, post: dict) -> bool:
        if len(self._config.post_languages) > 0:
            return post.language is None or post.language in self._config.post_languages
        return True

    def _is_interacted_post(self, post: dict) -> bool:
        return (
            post.reblogged
            or post.favourited
            or post.bookmarked
            or post.account.id == self._mastodon_user.id
            or post.in_reply_to_account_id == self._mastodon_user.id
        )

    def add_seen_post_url(self, url: str) -> None:
        self._seen_post_urls.add(url)

    def filter_posts(self, posts: list[dict]) -> tuple[list[dict], set[str]]:
        filtered_posts = []
        boost_posts_urls = set()
        for post in posts:
            boost = False
            if post.reblog is not None:
                post = post.reblog  # look at the boosted post
                boost = True

            if post.url in self._seen_post_urls:
                # print(f"Excluded seen post {post.url}")
                continue

            if (
                self._config.timeline_exclude_previously_digested_posts
                and post.url in self._digested_post_urls
            ):
                # print(f"Excluded seen post {post.url}")
                self._digested_post_count += 1
                continue

            if post.visibility == "direct":
                # print(f"Excluded direct post {post.url}")
                self._direct_post_count += 1
                continue

            if post.muted:
                # print(f"Excluded muted post {post.url}")
                self._muted_post_count += 1
                continue

            if self._is_interacted_post(post):
                # print(f"Excluded interacted post {post.url}")
                self._interacted_post_count += 1
                continue

            if post.created_at < self._min_post_created_at:
                # print(f"Excluded old post {post.url}")
                self._old_post_count += 1
                continue

            if self._config.timeline_exclude_trending and post.id in self._trending_post_ids:
                # print(f"Excluded trending post {post.url}")
                self._trending_post_count += 1
                continue

            if post.content in self._contents:
                # print(f"Excluded duplicate post {post.url}")
                self._duplicate_post_count += 1
                continue

            if not self._is_valid_lang_post(post):
                # print(f"Excluded foreign language post {post.url}")
                self._foreign_language_post_count += 1
                continue

            soup = BeautifulSoup(post.content, "html.parser")
            if self._is_short_post(post, soup):
                # print(f"Excluded short post {post.url}")
                self._short_post_count += 1
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
                    # print(f"Excluded post matching user's filters {post.url}")
                    self._filtered_post_count += 1
                    continue

            filtered_posts.append(post)
            if boost:
                boost_posts_urls.add(post.url)

        return (filtered_posts, boost_posts_urls)

    def print_stats(self):
        total_count = (
            self._direct_post_count
            + self._muted_post_count
            + self._interacted_post_count
            + self._old_post_count
            + self._digested_post_count
            + self._trending_post_count
            + self._duplicate_post_count
            + self._foreign_language_post_count
            + self._short_post_count
            + self._filtered_post_count
        )
        print(
            f"""Excluded posts:
    total_count = {total_count}
    direct_post_count = {self._direct_post_count}
    muted_post_count = {self._muted_post_count}
    interacted_post_count = {self._interacted_post_count}
    old_post_count = {self._old_post_count}
    digested_post_count = {self._digested_post_count}
    trending_post_count = {self._trending_post_count}
    duplicate_post_count = {self._duplicate_post_count}
    foreign_language_post_count = {self._foreign_language_post_count}
    short_post_count = {self._short_post_count}
    filtered_post_count = {self._filtered_post_count}"""
        )


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
    response: Optional[list[dict]] = mastodon_client.timeline(min_id=start, limit=40)
    while response and total_posts_seen < config.timeline_posts_limit:
        print("Fetched timeline posts")
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
        response = mastodon_client.fetch_previous(response)

    filterator.print_stats()

    total_count = len(posts) + len(boosts)
    for i, scored_post in enumerate(itertools.chain(posts, boosts)):
        if scored_post.fetch_metrics():
            print(f"[{i+1}/{total_count}] Fetched metrics for {scored_post.url}")

    return posts, boosts


def fetch_boosted_accounts(mastodon_client: Mastodon, boosted_lists: set[int]) -> set[str]:
    boosted_accounts: list[str] = []
    for id in boosted_lists:
        accounts = mastodon_client.list_accounts(id, limit="0")
        boosted_accounts.extend(account.acct for account in accounts)

    return set(boosted_accounts)


def get_known_instance_domains() -> set[str]:
    with requests.get("https://nodes.fediverse.party/nodes.json") as resp:
        domains = resp.json()
        assert type(domains) == list
        return set("://" + domain + "/" for domain in domains)
