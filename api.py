from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
import itertools

from models import ScoredPost

if TYPE_CHECKING:
    from mastodon import Mastodon


def fetch_posts_and_boosts(
    hours: int, 
    mastodon_client: Mastodon,
    mastodon_username: str,
    languages: set[str]
) -> tuple[list[ScoredPost], list[ScoredPost]]:
    """Fetches posts form the home timeline that the account hasn't interactied with"""

    TIMELINE_LIMIT = 1000

    # First, get our filters
    filters = mastodon_client.filters()

    # Set our start query
    start = datetime.now(timezone.utc) - timedelta(hours=hours)

    posts = []
    boosts = []
    seen_post_urls = set()
    total_posts_seen = 0
    filter_by_lang = \
      (lambda p: p['language'] is None or p['language'] in languages) if len(languages) > 0 else (lambda p: True)

    # Iterate over our home timeline until we run out of posts or we hit the limit
    response = mastodon_client.timeline(min_id=start, limit=40)
    while response and total_posts_seen < TIMELINE_LIMIT:
        print("Fetching timeline posts")
        # Apply our server-side filters
        if filters:
            filtered_response = mastodon_client.filters_apply(response, filters, "home")
        else:
            filtered_response = response

        for post in filtered_response:
            boost = False
            if post["reblog"] is not None:
                post = post["reblog"]  # look at the bosted post
                boost = True

            if post["visibility"] != "public" and post["visibility"] != "unlisted":
                continue

            if not filter_by_lang(post):
              continue

            scored_post = ScoredPost(post)  # wrap the post data as a ScoredPost

            if scored_post.url not in seen_post_urls:
                # Apply our local filters
                # Basically ignore my posts or posts I've interacted with
                if (
                    not scored_post.info["reblogged"]
                    and not scored_post.info["favourited"]
                    and not scored_post.info["bookmarked"]
                    and scored_post.info["account"]["acct"] != mastodon_username
                ):
                    total_posts_seen += 1
                    # Append to either the boosts list or the posts lists
                    if boost:
                        boosts.append(scored_post)
                    else:
                        posts.append(scored_post)
                    seen_post_urls.add(scored_post.url)

        response = mastodon_client.fetch_previous(
            response
        )  # fext the previous (because of reverse chron) page of results

    total_count = len(posts) + len(boosts)
    for i, post in enumerate(itertools.chain(posts, boosts)):
        print(f"[{i+1}/{total_count}] Fetching metrics for {post.url}")
        post.fetch_metrics()

    return posts, boosts

def fetch_boosted_accounts(mastodon_client: Mastodon, mastodon_username: str, boosted_lists: set[int]) -> set[str]:
  boosted_accounts = []
  for id in boosted_lists:
    accounts = mastodon_client.list_accounts(id, limit="0")
    boosted_accounts.extend(account['acct'] for account in accounts)

  return boosted_accounts
