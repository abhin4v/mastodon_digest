from collections import defaultdict
from config import Config
from enum import Enum
from itertools import chain
from models import ScoredPost
from scipy import stats
from scorers import Scorer
import numpy as np


class Threshold:
    def __init__(self, value: float) -> None:
        self.value = value

    def posts_meeting_criteria(
        self,
        posts: list[ScoredPost],
        boosted_accounts: set[str],
        config: Config,
        non_threshold_post_frac: float,
        scorer: Scorer,
    ) -> list[ScoredPost]:
        """Returns a list of ScoredPosts that meet this Threshold with the given Scorer"""

        for p in posts:
            p.calc_score(boosted_accounts, config, scorer)

        threads = self.group_posts_into_threads(posts)
        posts = self.choose_highest_scored_thread_posts(posts, threads)
        posts = self.choose_highest_scored_user_posts(posts, config.timeline_max_user_post_count)

        all_post_scores = [p.score for p in posts]
        threshold_posts = []
        non_threshold_posts = []
        for p in posts:
            if stats.percentileofscore(all_post_scores, p.score) >= self.value:
                threshold_posts.append(p)
            else:
                non_threshold_posts.append(p)

        threshold_posts.sort(key=lambda p: p.score, reverse=True)

        non_threshold_posts_sample = []
        if non_threshold_post_frac > 0:
            sample_size = int(non_threshold_post_frac * len(threshold_posts))
            if sample_size > 0:
                indices = np.random.choice(len(threshold_posts), size=sample_size, replace=False)
                non_threshold_posts_sample = [non_threshold_posts[i] for i in indices]

        return threshold_posts + non_threshold_posts_sample

    def group_posts_into_threads(self, posts: list[ScoredPost]) -> list[set[int]]:
        post_reply_to_id_map: dict[int, set[int]] = {}

        for post in posts:
            if post.in_reply_to_id is not None:
                post_reply_to_id_map[post.id] = {post.in_reply_to_id}

        while True:
            changed = False
            for id, reply_to_ids in post_reply_to_id_map.items():
                for reply_to_id in reply_to_ids:
                    if reply_to_id in post_reply_to_id_map:
                        parents = post_reply_to_id_map[reply_to_id]
                        for parent in parents:
                            if not (parent in reply_to_ids):
                                post_reply_to_id_map[id] = set(reply_to_ids)
                                post_reply_to_id_map[id].add(parent)
                                changed = True
            if not changed:
                break

        for id in list(post_reply_to_id_map.keys()):
            if id in post_reply_to_id_map:
                for reply_to_id in post_reply_to_id_map[id]:
                    if reply_to_id in post_reply_to_id_map:
                        del post_reply_to_id_map[reply_to_id]

        for id in post_reply_to_id_map:
            post_reply_to_id_map[id].add(id)

        return list(post_reply_to_id_map.values())

    def choose_highest_scored_thread_posts(
        self, posts: list[ScoredPost], threads: list[set[int]]
    ) -> list[ScoredPost]:
        posts_by_id: dict[int, ScoredPost] = {}
        for post in posts:
            posts_by_id[post.id] = post

        max_score_posts = [
            max(
                (
                    (post_id, posts_by_id[post_id].score)
                    for post_id in thread
                    if post_id in posts_by_id
                ),
                key=lambda item: item[1],
            )[0]
            for thread in threads
        ]

        for i, thread in enumerate(threads):
            for post_id in thread:
                if post_id == max_score_posts[i]:
                    continue
                if post_id in posts_by_id:
                    del posts_by_id[post_id]

        return list(posts_by_id.values())

    def choose_highest_scored_user_posts(
        self, posts: list[ScoredPost], max_post_count: int
    ) -> list[ScoredPost]:
        posts_by_user = defaultdict(list)
        for post in posts:
            posts_by_user[post.account["acct"]].append(post)

        for acct, user_posts in posts_by_user.items():
            posts_by_user[acct] = sorted(user_posts, key=lambda p: p.score, reverse=True)[
                :max_post_count
            ]

        return list(chain.from_iterable(posts_by_user.values()))
