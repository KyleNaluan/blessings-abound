"""The two mock sales channels, each a separate FastAPI service with its own role and schema.

They stand in for real platforms, so they import nothing from the main app, which reaches them
only over HTTP through the adapter in app/channels.py. See docs/architecture.md#mock-channels.
"""
