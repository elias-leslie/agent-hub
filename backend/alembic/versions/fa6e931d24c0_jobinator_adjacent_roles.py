"""Include bounded CV-grounded adjacent directions in employer discovery."""
from sqlalchemy import text

from alembic import op

revision = "fa6e931d24c0"
down_revision = "e95d820c13bf"
branch_labels = None
depends_on = None

INSTRUCTION = '''For task=company_discovery, include adjacent_roles alongside companies.
adjacent_roles contains zero to three objects: name (a specific role title), reason
(why the reviewed CV supports exploring this direction), cv_quote (an exact
substring of the supplied reviewed CV). Suggest only credible transfers of actual
skills, education or experience. Do not suggest a direction merely because its
pay is high or its title resembles a target. Exclude already supplied target
roles. Return no suggestions when evidence is weak. These are labeled suggestions,
not changes to the candidate's chosen priorities. All existing company discovery
source and verification requirements still apply.

'''


def upgrade() -> None:
    op.get_bind().execute(text("UPDATE agents SET system_prompt=:instruction || system_prompt, version=version+1 WHERE slug='jobs-company'"), {"instruction": INSTRUCTION})
    op.get_bind().execute(text("UPDATE agents SET system_prompt=replace(system_prompt, 'claims (list of candidate claims made)', 'claims (list of objects with sentence and cv_evidence strings; cv_evidence must quote the reviewed CV exactly)'), version=version+1 WHERE slug IN ('jobs-cover', 'jobs-cover-codex')"))


def downgrade() -> None:
    raise RuntimeError("Preserve canonical prompt history")
