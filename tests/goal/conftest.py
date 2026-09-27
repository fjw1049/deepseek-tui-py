import pytest


@pytest.fixture
def complete_goal():
    """Seed observed evidence when testing lifecycle rather than verification itself."""

    def complete(service):
        service.record_tool_result("verified", "read_file", {"path": "report"}, success=True)
        return service.mark_complete(
            "Verified",
            evidence=["verified"],
            audit={
                "checks": [
                    {
                        "requirement_id": item["id"],
                        "explanation": "Verified against report",
                        "evidence": ["verified"],
                    }
                    for item in service.snapshot().requirements
                ]
            },
        )

    return complete
