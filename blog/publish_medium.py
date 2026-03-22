"""
VoiceStax Blog Publisher to Medium
Reads a markdown blog post and publishes it to Medium via the API.
"""

import os
import re
import sys
import markdown
from pathlib import Path


def markdown_to_html(md_content: str) -> str:
    """
    Convert markdown to HTML with Medium-compatible formatting.
    Handles: headers, bold, italic, code blocks, inline code, lists, links, blockquotes.
    """

    # Pre-process: convert ```language ... ``` code blocks
    def code_block_replace(m):
        lang = m.group(1) or ""
        code = m.group(2)
        # Use Medium-compatible <pre> block
        return f"<pre>{code}</pre>"

    md_content = re.sub(r"```(\w+)?\n(.*?)```", code_block_replace, md_content, flags=re.DOTALL)

    # Pre-process: inline code
    md_content = re.sub(r"`([^`]+)`", r"<code>\1</code>", md_content)

    # Use markdown library for base conversion
    html = markdown.markdown(
        md_content,
        extensions=["fenced_code", "tables", "sane_lists"],
        extension_config={}
    )

    # Post-processing for Medium compatibility
    # Wrap paragraphs properly
    html = re.sub(r"<p>(<pre>.*?</pre>)</p>", r"\1", html, flags=re.DOTALL)
    html = re.sub(r"<p>(<code>.*?</code>)</p>", r"\1", html, flags=re.DOTALL)

    # Add target="_blank" to external links
    def link_replace(m):
        url = m.group(2)
        text = m.group(1)
        target = '_blank" rel="noopener' if url.startswith("http") else ""
        return f'<a href="{url}"{target}>{text}</a>'

    html = re.sub(r'<a href="([^"]+)">(.*?)</a>', link_replace, html)

    return html


def extract_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML-like frontmatter from markdown."""
    frontmatter = {}
    body = content

    if content.startswith("---"):
        end = content.find("\n---", 4)
        if end != -1:
            fm_block = content[4:end]
            body = content[end + 4:].lstrip("\n")
            for line in fm_block.split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    frontmatter[key.strip()] = val.strip().strip('"').strip("'")

    return frontmatter, body


def extract_tags(content: str) -> list[str]:
    """Extract #tag hashtags from content."""
    tags = re.findall(r"#(\w[-\w]*)", content)
    # Filter common English words that aren't useful tags
    stopwords = {"the", "and", "for", "with", "from", "this", "that", "you", "are", "was", "have", "has"}
    return [t for t in tags if t.lower() not in stopwords][:5]


def publish_to_medium(
    markdown_file: str,
    integration_token: str,
    publication_id: str = None
) -> dict:
    """
    Publish a markdown blog post to Medium.

    Args:
        markdown_file: Path to the markdown file
        integration_token: Medium integration token
        publication_id: Optional publication ID to post to

    Returns:
        dict with 'url' of the published post
    """
    import requests

    # Read and parse markdown
    md_content = Path(markdown_file).read_text(encoding="utf-8")
    frontmatter, body = extract_frontmatter(md_content)

    # Extract title from frontmatter or first H1
    title = frontmatter.get("title", "")
    if not title:
        h1_match = re.search(r"^# (.+)", body, re.MULTILINE)
        title = h1_match.group(1).strip() if h1_match else "Untitled"

    # Extract subtitle
    subtitle = frontmatter.get("subtitle", "")

    # Convert to HTML
    body = re.sub(r"^---.*?---\n", "", body, flags=re.DOTALL)  # Remove frontmatter
    body = re.sub(r"^# .+\n", "", body, count=1)  # Remove title from body
    html_content = markdown_to_html(body)

    # Extract tags from content
    tags = extract_tags(md_content)
    if "tags" in frontmatter:
        # Parse comma or space-separated tags from frontmatter
        extra_tags = re.findall(r"#(\w+)", frontmatter["tags"])
        tags = list(set(tags + extra_tags))[:5]

    # Build request
    headers = {
        "Authorization": f"Bearer {integration_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "title": title,
        "contentFormat": "html",
        "content": html_content,
        "tags": tags,
        "publishStatus": "draft",  # Set to "public" to auto-publish
    }

    if subtitle:
        payload["subtitle"] = subtitle

    # Determine endpoint
    if publication_id:
        url = f"https://api.medium.com/v1/publications/{publication_id}/posts"
    else:
        url = "https://api.medium.com/v1/users/me/posts"

    print(f"Publishing to: {'publication ' + publication_id if publication_id else 'personal blog'}")
    print(f"Title: {title}")
    print(f"Tags: {tags}")

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 201:
        print(f"Error: {response.status_code}")
        print(response.text)
        response.raise_for_status()

    result = response.json()
    data = result.get("data", {})
    publish_url = data.get("url", "https://medium.com (unknown)")

    print(f"\n✅ Published!")
    print(f"   URL: {publish_url}")
    print(f"   Note: Post is in DRAFT state. Go to Medium to review and publish it.")

    return {"url": publish_url, "data": data}


def main():
    if len(sys.argv) < 2:
        print("Usage: python publish_medium.py <markdown_file> --token <integration_token> [--publication-id <id>]")
        print()
        print("Steps to get an integration token:")
        print("  1. Go to https://medium.com/me/settings/security")
        print("  2. Scroll to 'Integration tokens'")
        print("  3. Generate a new token")
        print()
        print("Example:")
        print("  python publish_medium.py output.md --token xxxx")
        sys.exit(1)

    markdown_file = sys.argv[1]

    if "--token" not in sys.argv:
        print("Error: --token is required")
        sys.exit(1)

    token_idx = sys.argv.index("--token")
    integration_token = sys.argv[token_idx + 1] if token_idx + 1 < len(sys.argv) else None

    publication_id = None
    if "--publication-id" in sys.argv:
        pub_idx = sys.argv.index("--publication-id")
        publication_id = sys.argv[pub_idx + 1] if pub_idx + 1 < len(sys.argv) else None

    if not integration_token:
        print("Error: integration token not provided")
        sys.exit(1)

    if not Path(markdown_file).exists():
        print(f"Error: file not found: {markdown_file}")
        sys.exit(1)

    result = publish_to_medium(markdown_file, integration_token, publication_id)
    print(f"\nResult: {result}")


if __name__ == "__main__":
    main()
