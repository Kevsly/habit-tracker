def get_tags(note):
    if not note:
        return []
    # simple hashtag extraction
    tags = []
    for word in note.split():
        if word.startswith('#') and len(word) > 1:
            # strip punctuation
            tag = ''.join(c for c in word[1:] if c.isalnum() or c == '_')
            if tag:
                tags.append(tag.lower())
    # also allow comma-separated
    return tags


def add_tag_to_note(note, tag):
    tag = tag.strip().lstrip('#').lower()
    if not tag:
        return note
    if f'#{tag}' in note or tag in note.split():
        return note
    return f"{note} #{tag}" if note else f"#{tag}"
