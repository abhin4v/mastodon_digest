from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from scipy import stats
import numpy as np

if TYPE_CHECKING:
    from models import ScoredPost
    from scorers import Scorer


class Threshold(Enum):
    LAX = 90
    NORMAL = 95
    STRICT = 98

    def get_name(self):
        return self.name.lower()

    def posts_meeting_criteria(
        self, posts: list[ScoredPost],
        boosted_tags: set[str],
        halflife_hours: int,
        non_threshold_post_frac: float,
        scorer: Scorer
    ) -> list[ScoredPost]:
        """Returns a list of ScoredPosts that meet this Threshold with the given Scorer"""

        all_post_scores = [p.calc_score(boosted_tags, halflife_hours, scorer) for p in posts]
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

def get_thresholds():
    """Returns a dictionary mapping lowercase threshold names to values"""

    return {i.get_name(): i.value for i in Threshold}


def get_threshold_from_name(name: str) -> Threshold:
    """Returns Threshold for a given named string"""

    return Threshold[name.upper()]
