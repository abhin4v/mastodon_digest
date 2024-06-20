from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
import itertools
from bs4 import BeautifulSoup

from models import ScoredPost

if TYPE_CHECKING:
    from mastodon import Mastodon


def fetch_posts_and_boosts(
    hours: int,
    mastodon_client: Mastodon,
    languages: set[str],
    exclude_trending: bool
) -> tuple[list[ScoredPost], list[ScoredPost]]:
    """Fetches posts form the home timeline that the account hasn't interactied with"""
    mastodon_user = mastodon_client.me()
    print(f"Fetching data for {mastodon_user['username']}")

    trending_post_ids = set(p['id'] for p in mastodon_client.trending_statuses()) if exclude_trending else set()

    TIMELINE_LIMIT = 2000
    MIN_WORD_COUNT = 10

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

            if exclude_trending and post["id"] in trending_post_ids:
                print(f"Excluded trending post {post['url']}")
                continue

            if not filter_by_lang(post):
              continue

            soup = BeautifulSoup(post['content'], 'html.parser')
            if (
                len([word for word in soup.text.split() if not word.startswith('#')]) <= MIN_WORD_COUNT
                and len(post.media_attachments) == 0
                and post.poll is None
                and len(soup.find_all('a')) == 0
               ):
               print(f"Excluded short post {post['url']}")
               continue

            post['content'] = str(soup)
            scored_post = ScoredPost(post)  # wrap the post data as a ScoredPost

            if scored_post.url not in seen_post_urls:
                # Apply our local filters
                # Basically ignore my posts or posts I've interacted with
                if (
                    not scored_post.info["reblogged"]
                    and not scored_post.info["favourited"]
                    and not scored_post.info["bookmarked"]
                    and scored_post.info["account"]["id"] != mastodon_user["id"]
                    and scored_post.info["in_reply_to_account_id"] != mastodon_user["id"]
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

def fetch_boosted_accounts(mastodon_client: Mastodon, boosted_lists: set[int]) -> set[str]:
  boosted_accounts = []
  for id in boosted_lists:
    accounts = mastodon_client.list_accounts(id, limit="0")
    boosted_accounts.extend(account['acct'] for account in accounts)

  return boosted_accounts
