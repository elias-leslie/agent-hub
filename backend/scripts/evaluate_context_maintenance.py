"""Compare old and incremental review evidence preparation; never calls a model.

Run with -m scripts.evaluate_context_maintenance --output <new-receipt.json>.
Token estimates are not provider usage, billing, delivery or quality evidence.
"""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.db import async_session
from app.models.memory_unified import Memory
from app.models.prompt import Prompt
from app.models.runtime_context import RuntimeContextOverride
from app.services.context_policy import semantic_hash
from app.services.memory._review_agent_prompt import build_memory_review_prompt
from app.services.memory._review_agent_runner import DEFAULT_BATCH_LIMIT, _call_review_for_memories
from app.services.memory._review_agent_select import select_memories_due_for_review
from app.services.memory.budget import count_tokens
from app.services.memory.governance import collect_memory_governance_snapshot
from app.services.memory.tool_capability_context import format_tool_capability_context


async def capture(db,**kwargs): return kwargs['prompt'],None,None
async def main(output: Path):
 async with async_session() as db:
  selected=await select_memories_due_for_review(db,limit=DEFAULT_BATCH_LIMIT)
  memories=list((await db.execute(select(Memory).where(Memory.status=='active').order_by(Memory.scope,Memory.id))).scalars())
  prompts=list((await db.execute(select(Prompt).where(Prompt.enabled.is_(True)))).scalars())
  assignments=[{k:getattr(row,k) for k in ['consumer_profile','project_id','mode','enabled']}|{'prompt_slug':row.source_id} for row in (await db.execute(select(RuntimeContextOverride).where(RuntimeContextOverride.source_type=='prompt'))).scalars()]
  tools=await asyncio.to_thread(format_tool_capability_context,consumer_profile='agent_startup',bash_available=True)
  baseline=build_memory_review_prompt(selected,governance_snapshot=await collect_memory_governance_snapshot(db),memory_index=memories,authority_prompts=prompts,authority_prompt_assignments=assignments,computed_tool_capabilities=tools)
  current,_,_=await _call_review_for_memories(db,facade=SimpleNamespace(collect_memory_governance_snapshot=collect_memory_governance_snapshot,build_memory_review_prompt=build_memory_review_prompt,_call_reviewer_agent=capture),memories=selected,reviewer_agent_slug='memory-curator',reviewer_model_id=None)
  report={'method':'Same live selected memory batch and tokenizer; compare previous full-catalog evidence preparation with current applicable-candidate preparation. No model calls; not a native delivery or task-quality measurement.','selected_memories':len(selected),'selected_ids':[str(m.id) for m in selected],'baseline_estimated_input_tokens':count_tokens(baseline),'current_estimated_input_tokens':count_tokens(current),'baseline_sha256':semantic_hash(baseline),'current_sha256':semantic_hash(current),'model_calls':0,'quality':'Candidate narrowing is non-exhaustive and retains required co-applicable authority. No cheaper generative model qualification claimed.'}
  await asyncio.to_thread(output.write_text,json.dumps(report,indent=2)+'\n')
  print(json.dumps(report))
if __name__ == '__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output', type=Path, required=True)
 args=parser.parse_args()
 asyncio.run(main(args.output))
