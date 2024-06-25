import html

def format_post(post, mastodon_base_url) -> dict:

    def format_media(media, media_count):
        url = media["url"]
        description = html.escape(media["description"]) if media["description"] != None else ""
        caption = f"<figcaption>{description}</figcaption>" if media["description"] != None else ""
        formats = {
            'image': f'<a href="{url}"><figure><img src="{url}" alt="{description}"></img>{caption}</figure></a>',
            'video': f'<video src="{url}" controls width="100%"></video>',
            'gifv': f'<figure><video src="{url}" autoplay loop muted playsinline width="100%" alt="{description}"></video>{caption}</figure>'
        }
        if formats.__contains__(media.type):
            style = " style=\"max-width: calc(50% - 5px);\"" if media_count > 1 else "";
            return f'<div class="media"{style}>{formats[media.type]}</div>'
        else:
            return ""

    def format_displayname(display_name, emojis):
        for emoji in emojis:
            shortcode = html.escape(emoji["shortcode"])
            display_name = display_name.replace(f':{emoji["shortcode"]}:', f'<img title="{shortcode}" alt="{shortcode}" src="{emoji["url"]}">')
        return display_name

    account_avatar = post.data['account']['avatar']
    account_url = "https://main.elk.zone/" + post.data['account']['url']
    display_name = format_displayname(
        post.data['account']['display_name'],
        post.data['account']['emojis']
    )
    username = post.data['account']['username']
    content = post.data['content']
    media = "\n".join([format_media(media, len(post.data.media_attachments)) for media in post.data.media_attachments])
    # created_at = post.data['created_at'].strftime('%B %d, %Y at %H:%M')
    created_at = post.data['created_at'].isoformat()
    home_link = f'<a href="https://main.elk.zone/{post.get_home_url(mastodon_base_url)}" target="_blank">home</a>'
    original_link = f'<a href="{post.data.url}" target="_blank">original</a>'
    replies_count = post.data['replies_count']
    reblogs_count = post.data['reblogs_count']
    favourites_count = post.data['favourites_count']

    return dict(
        account_avatar=account_avatar,
        account_url=account_url,
        display_name=display_name,
        username=username,
        user_is_bot=post.data['account']['bot'],
        user_is_group=post.data['account']['group'],
        content=content,
        media=media,
        is_poll='poll' in post.data and post.data['poll'] is not None,
        created_at=created_at,
        home_link=home_link,
        original_link=original_link,
        replies_count=replies_count,
        reblogs_count=reblogs_count,
        favourites_count=favourites_count,
        score=f"{post.score:.2f}"
    )

def format_posts(posts, mastodon_base_url):
    return [format_post(post, mastodon_base_url) for post in posts]
