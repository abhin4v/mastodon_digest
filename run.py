from api import fetch_posts_and_boosts, fetch_boosted_accounts, get_known_instance_domains
from config import Config, read_config
from datetime import datetime
from formatters import format_posts
from jinja2 import Environment, FileSystemLoader
from mastodon import Mastodon
from pathlib import Path
from models import ScoredPost
from scorers import ExtendedSimpleWeightedScorer, Scorer
from thresholds import Threshold
import argparse
import itertools
import json
import os
import os
import pprint
import shutil
import sys
import tempfile


def render_digest(context: dict, output_dir: Path) -> None:
    environment = Environment(loader=FileSystemLoader("templates/"))
    template = environment.get_template("digest.html.jinja")
    output_html = template.render(context)
    output_file_path = output_dir / "index.html"
    output_file_path.write_text(output_html)
    print(f"Rendered digest: {len(context['posts'])} posts and {len(context['boosts'])} boosts")


def get_digested_posts(config: Config) -> list[str]:
    digested_posts_file = config.digest_digested_posts_file

    def createFile():
        with open(digested_posts_file, "w") as f:
            f.write("[]")
            return []

    if not os.path.isfile(digested_posts_file):
        return createFile()

    with open(digested_posts_file, "r") as f:
        try:
            post_urls = json.load(f)
            assert type(post_urls) == list
            return post_urls
        except json.JSONDecodeError:
            return createFile()


def save_digested_posts(
    digested_posts: list[str], posts: list[ScoredPost], boosts: list[ScoredPost], config: Config
) -> None:
    digested_posts.extend(post.url for post in itertools.chain(posts, boosts))
    digested_posts_count = int(
        config.timeline_posts_limit * config.post_max_age_hours / config.timeline_hours_limit
    )
    digested_posts = digested_posts[-digested_posts_count:]

    with tempfile.NamedTemporaryFile(
        "w", prefix="mastodon_digest_digested_posts", suffix=".json", delete=False
    ) as f:
        json.dump(digested_posts, f)
        tempPath = f.name

    shutil.move(tempPath, config.digest_digested_posts_file)
    print(f"Saved {len(digested_posts)} digested post URLs")


def run(
    config: Config,
    scorer: Scorer,
    mastodon_token: str,
    mastodon_base_url: str,
    output_dir: str,
) -> None:
    print(f"Running with config:")
    pprint.pp(config)

    hours = config.timeline_hours_limit
    print(f"Building digest from the past {hours} hours...")

    mastodon_client = Mastodon(
        access_token=mastodon_token,
        api_base_url=mastodon_base_url,
    )
    non_threshold_posts_frac = config.digest_explore_frac / (1 - config.digest_explore_frac)

    boosted_accounts = fetch_boosted_accounts(mastodon_client, config.digest_boosted_list_ids)
    digested_posts = get_digested_posts(config)
    print(f"Read {len(digested_posts)} digested post URLs")

    # 1. Fetch all the posts and boosts from our home timeline that we haven't interacted with
    posts, boosts = fetch_posts_and_boosts(set(digested_posts), mastodon_client, config)
    known_instance_domains = get_known_instance_domains()

    # 2. Score them, and return those that meet our threshold
    threshold = Threshold(config.digest_threshold)
    threshold_posts = threshold.posts_meeting_criteria(
        posts,
        boosted_accounts,
        config,
        non_threshold_posts_frac,
        scorer,
    )
    threshold_boosts = threshold.posts_meeting_criteria(
        boosts,
        boosted_accounts,
        config,
        non_threshold_posts_frac,
        scorer,
    )

    save_digested_posts(digested_posts, threshold_posts, threshold_boosts, config)

    # 3. Build the digest
    render_digest(
        context={
            "hours": hours,
            "posts": format_posts(threshold_posts, mastodon_base_url, known_instance_domains),
            "boosts": format_posts(threshold_boosts, mastodon_base_url, known_instance_domains),
            "mastodon_base_url": mastodon_base_url,
            "rendered_at": datetime.utcnow().isoformat() + "Z",
            "threshold": config.digest_threshold,
            "scorer": scorer.get_name(),
        },
        output_dir=Path(output_dir),
    )


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        prog="mastodon_digest",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arg_parser.add_argument(
        "output",
        default="./render/",
        help="Output directory for the rendered digest",
    )
    arg_parser.add_argument(
        "--config",
        default="config.toml",
        dest="config",
        help="The path to the config file",
        type=str,
    )

    args = arg_parser.parse_args()
    config = read_config(args.config)

    output_dir = Path(args.output)
    if not output_dir.exists() or not output_dir.is_dir():
        sys.exit(f"Output directory not found: {args.output_dir}")

    mastodon_token = os.getenv("MASTODON_TOKEN")
    mastodon_base_url = os.getenv("MASTODON_BASE_URL")

    if not mastodon_token:
        sys.exit("Missing environment variable: MASTODON_TOKEN")
    if not mastodon_base_url:
        sys.exit("Missing environment variable: MASTODON_BASE_URL")

    run(config, ExtendedSimpleWeightedScorer(), mastodon_token, mastodon_base_url, output_dir)
