async def test_browser_routes_require_auth_and_existing_thread(authed_client):
    client, token = authed_client
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        await client.get("/v1/threads/missing/browser", headers={"Authorization": ""})
    ).status_code == 401
    assert (await client.get("/v1/threads/missing/browser", headers=headers)).status_code == 404
    created = await client.post("/v1/threads", json={"title": "Browser test"}, headers=headers)
    thread_id = created.json()["id"]
    base = f"/v1/threads/{thread_id}/browser"
    response = await client.get(base, headers=headers)
    assert response.status_code == 200
    assert response.json()["active"] is False
    invalid = await client.post(
        base + "/action", json={"action": "open", "url": "file:///etc/passwd"}, headers=headers
    )
    assert invalid.status_code == 422
    no_session = await client.post(base + "/control", json={"owner": "user"}, headers=headers)
    assert no_session.status_code == 409
