from b24_migrator.services.planner import PlannerService


def test_plan_hash_is_deterministic() -> None:
    service = PlannerService()
    first = service.create_plan("https://a", "https://b", ["tasks", "crm"], job_id="job-1")
    second = service.create_plan("https://a", "https://b", ["crm", "tasks"], job_id="job-1")

    assert first.plan_id == second.plan_id
    assert first.deterministic_hash == second.deterministic_hash
