from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Type
import math
import tomllib


class TypedDescriptor:
    def __init__(self, *, default: Any, type_: Type) -> None:
        self._default = default
        self.type_ = type_

    def __set_name__(self, owner: Any, name: str) -> None:
        self._name = "_" + name

    def __get__(self, obj: Any, type: Type) -> Any:
        if obj is None:
            return self._default

        return getattr(obj, self._name, self._default)

    def _check_type(self, value: Any) -> bool:
        if value is None:
            return False
        if type(value) == self.type_:
            return True
        else:
            raise AttributeError(f"{value} is not of type: {self.type_}")

    def __set__(self, obj: Any, value: Any) -> None:
        if self._check_type(value):
            setattr(obj, self._name, value)


class SetDescriptor(TypedDescriptor):
    def __init__(self, *, subtype: Type) -> None:
        super().__init__(default=frozenset, type_=frozenset)
        self.subtype = subtype

    def __set__(self, obj: Any, value: Any) -> None:
        if self._check_type(value):
            for i in value:
                if type(i) != self.subtype:
                    raise AttributeError(f"{i} is not of type: {self.subtype}")
            setattr(obj, self._name, value)


class RangedTypedDescriptor(TypedDescriptor):
    def __init__(self, *, default: Any, type_: Type, min_value: Any, max_value: Any) -> None:
        super().__init__(default=default, type_=type_)
        self._min_value = min_value
        self._max_value = max_value

    def __set__(self, obj: Any, value: Any) -> None:
        if self._check_type(value):
            if value >= self._min_value and value <= self._max_value:
                setattr(obj, self._name, value)
            else:
                raise AttributeError(
                    f"{value} is not in range {self._min_value} to {self._max_value}"
                )


class IntDescriptor(RangedTypedDescriptor):
    def __init__(self, *, default: Any, min_value: Any, max_value: Any) -> None:
        super().__init__(default=default, type_=int, min_value=min_value, max_value=max_value)


class FloatDescriptor(RangedTypedDescriptor):
    def __init__(self, *, default: Any, min_value: Any, max_value: Any) -> None:
        super().__init__(default=default, type_=float, min_value=min_value, max_value=max_value)


@dataclass
class Config:
    timeline_posts_limit: IntDescriptor = IntDescriptor(
        default=2000, min_value=1000, max_value=4000
    )
    timeline_hours_limit: IntDescriptor = IntDescriptor(default=24, min_value=1, max_value=24)
    timeline_exclude_trending: TypedDescriptor = TypedDescriptor(default=False, type_=bool)
    timeline_exclude_previously_digested_posts: TypedDescriptor = TypedDescriptor(
        default=False, type_=bool
    )
    timeline_max_user_post_count: IntDescriptor = IntDescriptor(
        default=3, min_value=1, max_value=math.inf
    )
    post_min_word_count: IntDescriptor = IntDescriptor(default=10, min_value=3, max_value=1000)
    post_max_age_hours: IntDescriptor = IntDescriptor(default=36, min_value=1, max_value=240)
    post_languages: SetDescriptor = SetDescriptor(subtype=str)
    scoring_tag_boost: FloatDescriptor = FloatDescriptor(default=1.2, min_value=1, max_value=2)
    scoring_account_boost: FloatDescriptor = FloatDescriptor(default=1.2, min_value=1, max_value=2)
    scoring_reply_unboost: FloatDescriptor = FloatDescriptor(default=1.5, min_value=1, max_value=2)
    scoring_halflife_hours: IntDescriptor = IntDescriptor(default=0, min_value=1, max_value=24)
    scoring_tag_count_threshold: IntDescriptor = IntDescriptor(default=3, min_value=1, max_value=10)
    digest_explore_frac: FloatDescriptor = FloatDescriptor(
        default=0.0, min_value=0.0, max_value=0.5
    )
    digest_threshold: IntDescriptor = IntDescriptor(default=90, min_value=0, max_value=99)
    digest_boosted_tags: SetDescriptor = SetDescriptor(subtype=str)
    digest_unboosted_tags: SetDescriptor = SetDescriptor(subtype=str)
    digest_boosted_list_ids: SetDescriptor = SetDescriptor(subtype=int)
    digest_digested_posts_file: TypedDescriptor = TypedDescriptor(
        default="digested_posts.json", type_=str
    )


def validate_config(config: dict) -> Config:
    timeline = defaultdict(lambda: None) | config["timeline"]
    post = defaultdict(lambda: None) | config["post"]
    scoring = defaultdict(lambda: None) | config["scoring"]
    digest = defaultdict(lambda: None) | config["digest"]

    return Config(
        timeline_posts_limit=timeline["posts_limit"],
        timeline_hours_limit=timeline["hours_limit"],
        timeline_exclude_trending=timeline["exclude_trending"],
        timeline_exclude_previously_digested_posts=timeline["exclude_previously_digested_posts"],
        timeline_max_user_post_count=timeline["max_user_post_count"],
        post_min_word_count=post["min_word_count"],
        post_max_age_hours=post["max_age_hours"],
        post_languages=frozenset(l.lower() for l in post.get("languages", [])),
        scoring_tag_boost=scoring["tag_boost"],
        scoring_account_boost=scoring["account_boost"],
        scoring_reply_unboost=scoring["reply_unboost"],
        scoring_halflife_hours=scoring["halflife_hours"],
        scoring_tag_count_threshold=scoring["tag_count_threshold"],
        digest_explore_frac=digest["explore_frac"],
        digest_threshold=digest["threshold"],
        digest_boosted_tags=frozenset(t.lower() for t in digest.get("boosted_tags", [])),
        digest_unboosted_tags=frozenset(t.lower() for t in digest.get("unboosted_tags", [])),
        digest_boosted_list_ids=frozenset(digest.get("boosted_list_ids", [])),
        digest_digested_posts_file=digest["digested_posts_file"],
    )


def read_config(path: str) -> Config:
    with open(path, "rb") as f:
        return validate_config(tomllib.load(f))
