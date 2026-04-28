import pytest


@pytest.mark.asyncio
async def test_search_tasks_filters_st_task_payload(monkeypatch):
    from app.api import tasks as task_api

    async def fake_task_list(project_id: str, status: str | None, limit: int) -> dict:
        assert project_id == "agent-hub"
        assert status == "pending"
        assert limit == 25
        return {
            "tasks": [
                {
                    "id": "task-11111111",
                    "project_id": "agent-hub",
                    "title": "Fix chat task picker",
                    "description": "Search by title.",
                    "status": "pending",
                    "priority": 1,
                    "task_type": "feature",
                },
                {
                    "id": "task-22222222",
                    "project_id": "agent-hub",
                    "title": "Unrelated",
                    "description": "No match.",
                    "status": "pending",
                },
            ],
        }

    monkeypatch.setattr(task_api, "_run_st_task_list", fake_task_list)

    result = await task_api.search_tasks(project_id="agent-hub", q="picker", status="pending", limit=25)

    assert result.total == 1
    assert result.tasks[0].id == "task-11111111"
    assert result.tasks[0].title == "Fix chat task picker"
    assert result.tasks[0].priority == 1
