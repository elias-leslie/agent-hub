"""Re-pick the model for each Codex-side Jobinator agent from its own output.

Every agent below was re-decided on documents this migration's author generated
and read, not on benchmarks and not on the family being new. Four move and one
does not, which is the point: 5.6 being available is not a reason to use it.

The subscription serves codex/gpt-5.6-{sol,terra,luna} and codex/gpt-6-astra
(verified in f1a9c37d2b64). Astra is registered but used nowhere here -- nothing
Jobinator does is "the hardest end-to-end work", and at $10/$50 per 1M it is the
sledgehammer this project was told not to reach for.

jobs-tailor -- UNCHANGED, stays on codex/gpt-5.4-mini
    Four models drafted resumes for postings 4000 and 4039 from identical
    inputs. Fact fidelity decided it, because a tailored resume is the document
    that gets sent to an employer. Claims checked by hand against the CV:
        5.4-mini  no drift on either posting
        terra     "10,000 users" on BOTH postings; the CV says 10,000+ endpoints
        luna      the same drift on 4039, plus "900 users" for a CV that says
                  900+ faculty, staff and students
        sol       slowest (127s vs 35s), the most unspecific bullets (3 vs 1),
                  and it padded the skills line with "Huntress Managed EDR",
                  "Huntress Managed ITDR" and "Huntress Managed SIEM" as three
                  separate skills
    The bigger models wrote more specific-sounding prose partly by restating
    facts more loosely. mini stays.

jobs-critic-codex -- codex/gpt-5.4-mini -> codex/gpt-5.6-terra
    Judgement with short output, which is where reasoning effort earns its
    tokens. Each critic reviewed the same real draft carrying a drift verified
    by hand ("10,000 users" against a CV saying 10,000+ endpoints):
        5.4-mini  MISSED it twice out of two. Worse, three of its four blocking
                  "fabrication" findings quoted the *job posting's* own
                  requirement lines back as if the resume had claimed them.
        terra     caught it 3/3, each time as exactly one blocking finding with
                  the right span and the right reason, in 18-31s
        luna      caught it 2/2 but is not calibrated: one run filed 1 blocking
                  finding, the next filed 5, including pedantry about "63"
                  versus "approximately 63"
        sol       caught it, but also filed a false blocking fabrication against
                  "Microsoft Sentinel", which is in the CV -- and took 52s
    This is the registration the task brief was written about: the critic had
    been left on whatever was already registered, and it does not do the job.

jobs-cover-codex -- codex/gpt-5.4-mini -> codex/gpt-5.6-terra
    The candidate's own cover letter is 3,960 characters and the density floor
    is 3,300. mini wrote 3,535 -- clearing the floor by 7% and coming in shorter
    than anything the candidate has actually sent, with a closing that reached
    for "sharper, faster, and harder to ignore". terra wrote 4,341, the nearest
    of the four to the real letter, and structured it as a narrative with named
    specifics. luna wrote 5,216, a third longer than the candidate writes. All
    four passed every gate, so the gates did not decide this; reading them did.

jobs-evaluator-codex -- codex/gpt-5.4-mini -> codex/gpt-5.6-terra
    On a clear-fit posting all three models agreed at 4.8, so the difference
    only appears where judgement is actually required. On Huntress' Staff
    Product Manager, SIEM -- a role the candidate has no PM tenure for, at a
    company whose SIEM he adopted and championed -- mini scored 2.7 and would
    have filtered it out. terra scored 4.1, named the same blocker mini named,
    surfaced the Huntress connection mini underweighted, and said what to do
    about it: apply, but position as product ownership rather than as a general
    security executive. That is the more useful reading for a job search.

jobs-prep -- codex/gpt-5.4-mini -> codex/gpt-5.6-luna
    The story bank is empty, and the prompt says so in as many words: "The story
    bank is empty. Do not invent stories for the candidate." mini returned ten
    story matches anyway, with invented story titles and confidence scores of
    0.96 and 0.98. terra and luna both correctly returned none. Between the two
    compliant models the briefs are comparable, so this takes the cheaper tier:
    an interview brief is preparation the candidate reads and adapts, not a
    document that goes to an employer.

The Gemini-side agents -- jobs-cover, jobs-evaluator, jobs-screener,
jobs-company, jobs-critic-gemini, jobs-tailor-gemini -- are deliberately
untouched, and not for lack of looking. The second-opinion design depends on the
two sides being different families; moving any of them onto a 5.6 model would
turn a cross-family second opinion into a same-family one, which is the failure
the whole module exists to prevent. The screener is also high-volume
classification already running on a free tier, with the least to gain of any
agent here.

Fallback chains follow the rule set in e83b1d4f0a72: an in-family rung always
ahead of a cross-family one, and no cross-family rung at all for an agent whose
job is to be the second family. jobs-critic-codex, jobs-evaluator-codex and
jobs-cover-codex are all one side of a cross-family pairing, so all three stay
in-family for their whole chain. jobs-prep is not, so it keeps one Gemini rung,
last, so a brief still gets written during a Codex outage -- on 3.7-flash rather
than 3.8-flash, whose per-project quota was exhausted on both rotating accounts.

codex/gpt-5.4-mini is kept out of the critic and evaluator chains entirely.
A fallback that cannot do the job is not a fallback.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "b7d5e9c31f28"
down_revision: str | Sequence[str] | None = "f1a9c37d2b64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: slug -> (primary model, ordered fallbacks). thinking_level is untouched
#: everywhere: each model above was measured at the level its agent already
#: runs at, so the measurements transfer only if the level stays put.
_CHOSEN: dict[str, tuple[str, list[str]]] = {
    "jobs-critic-codex": (
        "codex/gpt-5.6-terra",
        ["codex/gpt-5.6-luna", "codex/gpt-5.6-sol", "codex/gpt-5.4"],
    ),
    "jobs-evaluator-codex": (
        "codex/gpt-5.6-terra",
        ["codex/gpt-5.6-luna", "codex/gpt-5.6-sol", "codex/gpt-5.4"],
    ),
    "jobs-cover-codex": (
        "codex/gpt-5.6-terra",
        ["codex/gpt-5.6-luna", "codex/gpt-5.6-sol", "codex/gpt-5.4-mini"],
    ),
    "jobs-prep": (
        "codex/gpt-5.6-luna",
        ["codex/gpt-5.6-terra", "codex/gpt-5.4-mini", "codex/gpt-5.4", "gemini-3.7-flash"],
    ),
}

#: What each agent was before, so the downgrade restores the exact chain rather
#: than a plausible-looking one.
_PREVIOUS: dict[str, tuple[str, list[str]]] = {
    "jobs-critic-codex": ("codex/gpt-5.4-mini", ["codex/gpt-5.4", "codex/gpt-5.5"]),
    "jobs-evaluator-codex": ("codex/gpt-5.4-mini", ["codex/gpt-5.4", "codex/gpt-5.5"]),
    "jobs-cover-codex": ("codex/gpt-5.4-mini", ["codex/gpt-5.4", "codex/gpt-5.5"]),
    "jobs-prep": (
        "codex/gpt-5.4-mini",
        ["codex/gpt-5.4", "codex/gpt-5.5", "gemini-3.8-flash", "gemini-3.7-flash"],
    ),
}

_UPDATE = text(
    """
    UPDATE agents
       SET primary_model_id = :model,
           fallback_models = CAST(:chain AS JSON),
           updated_at = now()
     WHERE slug = :slug
    """
)

#: Probe registrations used to generate the documents this decision rests on.
#: They exist only to let a second model run an identical prompt, since the
#: per-call model override is deprecated and ignored.
_PROBE_LIKE = "jobs-%-probe-%"


def _apply(chosen: dict[str, tuple[str, list[str]]]) -> None:
    bind = op.get_bind()
    for slug, (model, chain) in chosen.items():
        bind.execute(_UPDATE, {"slug": slug, "model": model, "chain": json.dumps(chain)})


def upgrade() -> None:
    _apply(_CHOSEN)
    op.get_bind().execute(
        text("DELETE FROM agents WHERE slug LIKE :pattern"), {"pattern": _PROBE_LIKE}
    )


def downgrade() -> None:
    _apply(_PREVIOUS)
