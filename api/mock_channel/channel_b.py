"""Channel B, a Depop or Poshmark-style resale app that takes clothing only and needs a brand.

Usage: uvicorn mock_channel.channel_b:app --port 8002
"""

from mock_channel.service import ChannelSpec, create_app

SPEC = ChannelSpec(
    schema_name="channel_b",
    label="Channel B",
    tagline="A resale app for clothing",
    categories=("apparel",),
    required=("brand",),
)

app = create_app(SPEC)
