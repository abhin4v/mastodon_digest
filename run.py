from api import fetch_posts_and_boosts, fetch_boosted_accounts, get_known_instance_domains
from config import Config, read_config
from datetime import datetime
from formatters import format_posts
from jinja2 import Environment, FileSystemLoader
from mastodon import Mastodon
from pathlib import Path
from scorers import ExtendedSimpleWeightedScorer, Scorer
from thresholds import Threshold
import argparse
import os
import pprint
import sys


def render_digest(context: dict, output_dir: Path) -> None:
    environment = Environment(loader=FileSystemLoader("templates/"))
    template = environment.get_template("digest.html.jinja")
    output_html = template.render(context)
    output_file_path = output_dir / "index.html"
    output_file_path.write_text(output_html)
    print("Rendered digest")


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

    # 1. Fetch all the posts and boosts from our home timeline that we haven't interacted with
    posts, boosts = fetch_posts_and_boosts(mastodon_client, config)
    known_instance_domains = get_known_instance_domains()

    # 2. Score them, and return those that meet our threshold
    threshold = Threshold(config.digest_threshold)
    threshold_posts = format_posts(
        threshold.posts_meeting_criteria(
            posts,
            boosted_accounts,
            config,
            non_threshold_posts_frac,
            scorer,
        ),
        mastodon_base_url,
        known_instance_domains
    )
    threshold_boosts = format_posts(
        threshold.posts_meeting_criteria(
            boosts,
            boosted_accounts,
            config,
            non_threshold_posts_frac,
            scorer,
        ),
        mastodon_base_url,
        known_instance_domains
    )

    # 3. Build the digest
    render_digest(
        context={
            "hours": hours,
            "posts": threshold_posts,
            "boosts": threshold_boosts,
            "mastodon_base_url": mastodon_base_url,
            "rendered_at": datetime.utcnow().isoformat() + "Z",
            "threshold": config.digest_threshold,
            "scorer": scorer.get_name(),
        },
        output_dir=output_dir,
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

    run(
        config,
        ExtendedSimpleWeightedScorer(),
        mastodon_token,
        mastodon_base_url,
        output_dir
    )
