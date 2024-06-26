from bs4 import BeautifulSoup
from config import Config
from datetime import datetime, timedelta, timezone
from mastodon import Mastodon
from models import ScoredPost
from typing import Optional
import itertools
import requests


def fetch_posts_and_boosts(
    mastodon_client: Mastodon,
    config: Config,
) -> tuple[list[ScoredPost], list[ScoredPost]]:
    """Fetches posts form the home timeline that the account hasn't interacted with"""
    mastodon_user = mastodon_client.me()
    print(f"Fetching data for {mastodon_user['username']}")

    trending_post_ids = (
        set(p["id"] for p in mastodon_client.trending_statuses())
        if config.timeline_exclude_trending
        else set()
    )

    # First, get our filters
    filters = mastodon_client.filters()

    # Set our start query
    start = datetime.now(timezone.utc) - timedelta(hours=config.timeline_hours_limit)

    min_post_created_at = datetime.now(timezone.utc) - timedelta(hours=config.post_max_age_hours)

    known_instance_domains = set()
    with requests.get("https://nodes.fediverse.party/nodes.json") as resp:
        domains = resp.json()
        assert type(domains) == list
        known_instance_domains = set("://" + domain + "/" for domain in domains)

    posts: list[ScoredPost] = []
    boosts: list[ScoredPost] = []
    seen_post_urls: set[str] = set()
    total_posts_seen = 0

    def filter_by_lang(post: dict) -> bool:
        if len(config.post_languages) > 0:
            return post["language"] is None or post["language"] in config.post_languages
        return True

    # Iterate over our home timeline until we run out of posts or we hit the limit
    response: Optional[list[dict]] = mastodon_client.timeline(min_id=start, limit=40)
    while response and total_posts_seen < config.timeline_posts_limit:
        print("Fetching timeline posts")
        # Apply our server-side filters
        filtered_response: list[dict] = response
        if filters:
            filtered_response = mastodon_client.filters_apply(response, filters, "home")

        for post in filtered_response:
            boost = False
            if post["reblog"] is not None:
                post = post["reblog"]  # look at the boosted post
                boost = True

            if post["created_at"] < min_post_created_at:
                print(f"Excluded old post {post['url']}")
                continue

            if post["visibility"] != "public" and post["visibility"] != "unlisted":
                continue

            if config.timeline_exclude_trending and post["id"] in trending_post_ids:
                print(f"Excluded trending post {post['url']}")
                continue

            if not filter_by_lang(post):
                continue

            soup = BeautifulSoup(post["content"], "html.parser")
            words = [
                word
                for word in soup.text.split()
                if not (word.startswith("#") or word.startswith("@") or word.startswith("http"))
            ]
            if len(words) == 0:
                continue

            if (
                len(words) <= config.post_min_word_count
                and len(post["media_attachments"]) == 0
                and post["poll"] is None
                and len(
                    soup.find_all(
                        lambda tag: tag.name == "a" and "mention" not in tag.attrs.get("class", [])
                    )
                )
                == 0
            ):
                print(f"Excluded short post {post['url']}")
                continue

            for mention in soup.find_all("a", class_="mention"):
                mention.attrs["href"] = "https://main.elk.zone/" + mention.attrs["href"]

            post["content"] = str(soup)
            scored_post = ScoredPost(post)  # wrap the post data as a ScoredPost

            if scored_post.url not in seen_post_urls:
                # Apply our local filters
                # Basically ignore my posts or posts I've interacted with
                if (
                    not scored_post.reblogged
                    and not scored_post.favourited
                    and not scored_post.bookmarked
                    and scored_post.account["id"] != mastodon_user["id"]
                    and scored_post.in_reply_to_account_id != mastodon_user["id"]
                ):
                    total_posts_seen += 1
                    # Append to either the boosts list or the posts lists
                    if boost:
                        boosts.append(scored_post)
                    else:
                        posts.append(scored_post)
                    seen_post_urls.add(scored_post.url)

        # fetch the previous (because of reverse chron) page of results
        response = mastodon_client.fetch_previous(response)

    total_count = len(posts) + len(boosts)
    for i, scored_post in enumerate(itertools.chain(posts, boosts)):
        soup = BeautifulSoup(scored_post.content, "html.parser")
        non_mention_links = soup.find_all(
            lambda tag: tag.name == "a" and "mention" not in tag.attrs.get("class", [])
        )
        for link in non_mention_links:
            if "href" in link.attrs and any(
                link.attrs["href"].find(domain) != -1 for domain in known_instance_domains
            ):
                link.attrs["href"] = "https://main.elk.zone/" + link.attrs["href"]

        scored_post.set_content(str(soup))
        print(f"[{i+1}/{total_count}] Fetching metrics for {scored_post.url}")
        scored_post.fetch_metrics()

    return posts, boosts


def fetch_boosted_accounts(mastodon_client: Mastodon, boosted_lists: set[int]) -> set[str]:
    boosted_accounts: list[str] = []
    for id in boosted_lists:
        accounts = mastodon_client.list_accounts(id, limit="0")
        boosted_accounts.extend(account["acct"] for account in accounts)

    return set(boosted_accounts)
