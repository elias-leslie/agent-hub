"""Support agents for specialized tasks.

Includes: supervisor, analyst, validator, explorer, specifier, designer, reasoner, qa, summarizer,
memory-rater, learning-extractor, voice-responder, complexity-assessor, critic

Agent definitions are organized in focused sub-modules:
- _support_coordination: supervisor, qa
- _support_analysis:     analyst, explorer, critic
- _support_memory:       summarizer, memory-rater, learning-extractor
- _support_utility:      validator, designer, reasoner, voice-responder, complexity-assessor
"""

from ._support_analysis import ANALYSIS_AGENTS
from ._support_coordination import COORDINATION_AGENTS
from ._support_memory import MEMORY_AGENTS
from ._support_utility import UTILITY_AGENTS

# Preserve the original ordering of agents.
# Original order: supervisor, analyst, validator, explorer, specifier, designer, reasoner,
#                 qa, summarizer, memory-rater, learning-extractor,
#                 voice-responder, complexity-assessor, critic
_supervisor = COORDINATION_AGENTS[0]
_qa = COORDINATION_AGENTS[1]
_analyst, _explorer, _specifier, _critic = (
    ANALYSIS_AGENTS[0],
    ANALYSIS_AGENTS[1],
    ANALYSIS_AGENTS[2],
    ANALYSIS_AGENTS[3],
)
_validator, _designer, _reasoner, _voice_responder, _complexity_assessor, _site_checker = (
    UTILITY_AGENTS[0],
    UTILITY_AGENTS[1],
    UTILITY_AGENTS[2],
    UTILITY_AGENTS[3],
    UTILITY_AGENTS[4],
    UTILITY_AGENTS[5],
)
_summarizer, _memory_rater, _learning_extractor = (
    MEMORY_AGENTS[0],
    MEMORY_AGENTS[1],
    MEMORY_AGENTS[2],
)

SUPPORT_AGENTS: list[dict[str, object]] = [
    _supervisor,
    _analyst,
    _validator,
    _explorer,
    _specifier,
    _designer,
    _reasoner,
    _qa,
    _summarizer,
    _memory_rater,
    _learning_extractor,
    _voice_responder,
    _complexity_assessor,
    _critic,
    _site_checker,
]
