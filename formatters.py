from bs4 import BeautifulSoup
from models import ScoredPost
import html


def fix_post_links(post: ScoredPost, known_instance_domains: set[str]) -> str:
    soup = BeautifulSoup(post.content, "html.parser")

    for mention in soup.find_all("a", class_="mention"):
        mention.attrs["href"] = "https://main.elk.zone/" + mention.attrs["href"]

    non_mention_links = soup.find_all(
        lambda tag: tag.name == "a" and "mention" not in tag.attrs.get("class", [])
    )
    for link in non_mention_links:
        if "href" in link.attrs and any(
            link.attrs["href"].find(domain) != -1 for domain in known_instance_domains
        ):
            link.attrs["href"] = "https://main.elk.zone/" + link.attrs["href"]

    return str(soup)


def replace_emojis(content: str, emojis: list[dict]) -> str:
    for emoji in emojis:
        shortcode = html.escape(emoji.shortcode)
        content = content.replace(
            f":{emoji.shortcode}:",
            f'<img class="emoji" title="{shortcode}" alt="{shortcode}" src="{emoji.url}">',
        )
    return content


def format_media(media: dict, media_count: int) -> str:
    url = media.url
    description = html.escape(media.description) if media.description != None else ""
    caption = f"<figcaption>{description}</figcaption>" if media.description != None else ""
    formats = {
        "image": f'<a href="{url}"><figure><img src="{url}" alt="{description}"></img>{caption}</figure></a>',
        "video": f'<video src="{url}" controls width="100%"></video>',
        "gifv": f'<figure><video src="{url}" autoplay loop muted playsinline width="100%" alt="{description}"></video>{caption}</figure>',
    }
    if media.type in formats:
        style = ' style="max-width: calc(50% - 5px);"' if media_count > 1 else ""
        return f'<div class="media"{style}>{formats[media.type]}</div>'
    else:
        return ""


def format_post(post: ScoredPost, mastodon_base_url: str, known_instance_domains: set[str]) -> dict:
    account_avatar = post.account.avatar
    account_url = "https://main.elk.zone/" + post.account.url
    display_name = replace_emojis(post.account.display_name, post.account.emojis)
    username = post.account.username
    content = replace_emojis(fix_post_links(post, known_instance_domains), post.emojis)
    media = "\n".join(
        [format_media(media, len(post.media_attachments)) for media in post.media_attachments]
    )
    created_at = post.created_at.isoformat()
    home_link = f'<a href="https://main.elk.zone/{post.get_home_url(mastodon_base_url)}" target="_blank">home</a>'
    original_link = f'<a href="{post.url}" target="_blank">original</a>'
    replies_count = post.replies_count
    reblogs_count = post.reblogs_count
    favourites_count = post.favourites_count

    return dict(
        account_avatar=account_avatar,
        account_url=account_url,
        display_name=display_name,
        username=username,
        user_is_bot=post.account.bot,
        user_is_group=post.account.group,
        sensitive=post.sensitive,
        spoiler_text=replace_emojis(post.spoiler_text, post.emojis),
        content=content,
        media=media,
        is_poll="poll" in post._data and post.poll is not None,
        created_at=created_at,
        home_link=home_link,
        original_link=original_link,
        replies_count=replies_count,
        reblogs_count=reblogs_count,
        favourites_count=favourites_count,
        score=f"{post.score:.2f}",
    )


def format_posts(
    posts: list[ScoredPost], mastodon_base_url: str, known_instance_domains: set[str]
) -> list[dict]:
    return [format_post(post, mastodon_base_url, known_instance_domains) for post in posts]
