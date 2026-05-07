"""Agent slug constants for Agent Hub client callers.

Model IDs live in Agent Hub's backend model catalog. Client code should route
work through agents so model swaps happen in one place.
"""

CHAT_AGENT = "chat"
CODER_AGENT = "coder"
REASONER_AGENT = "reasoner"
REVIEWER_AGENT = "reviewer"
IMAGE_AGENT = "image-gen"
PROMPT_BUILDER_AGENT = "prompt-builder"

DEFAULT_AGENT = CHAT_AGENT
DEFAULT_IMAGE_AGENT = IMAGE_AGENT
