def test_settings_defaults_and_update(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["values"]["backup.time"] == "02:00"
    assert body["values"]["upload.max_mb"] == 100
    assert body["data_dir"]

    r = client.patch("/api/settings", json={"backup.time": "03:30", "upload.max_mb": 50})
    assert r.status_code == 200
    assert r.json()["values"]["backup.time"] == "03:30"
    events = client.get("/api/events", params={"entity_type": "setting"}).json()["items"]
    assert {e["entity_id"] for e in events} >= {"backup.time", "upload.max_mb"}
    client.patch("/api/settings", json={"backup.time": "02:00", "upload.max_mb": 100})


def test_settings_validation(client):
    r = client.patch("/api/settings", json={"backup.time": "25:00", "nope": 1, "upload.max_mb": "x"})
    assert r.status_code == 422
    fields = r.json()["error"]["details"]["fields"]
    assert set(fields) == {"backup.time", "nope", "upload.max_mb"}
    assert client.get("/api/settings").json()["values"]["backup.time"] == "02:00"
