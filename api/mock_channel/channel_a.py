"""Channel A, an eBay-style marketplace that takes clothing, electronics and games.

Usage: uvicorn mock_channel.channel_a:app --port 8001
"""

from mock_channel.service import ChannelSpec, create_app

SPEC = ChannelSpec(
    schema_name="channel_a",
    label="Channel A",
    tagline="A marketplace for clothing, electronics and games",
    categories=(
        "Video Games",
        "Video Game Consoles",
        "Controllers & Attachments",
        "Video Game Accessories",
        "Men's Clothing",
        "Men's Shoes",
        "Women's Clothing",
        "Women's Shoes",
        "Kids' Clothing",
        "Kids' Shoes",
        "Unisex Clothing",
        "Unisex Shoes",
    ),
)

app = create_app(SPEC)
