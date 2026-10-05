from app.mcp_auth import generate_pat, list_tokens, revoke_token, validate_token


def test_pat_lifecycle(tmp_path, monkeypatch):
    tokens_file = tmp_path / "mcp_tokens.json"
    monkeypatch.setattr("app.mcp_auth.RUNTIME_DIR", tmp_path)
    monkeypatch.setattr("app.mcp_auth.TOKENS_FILE", tokens_file)

    # Initially empty
    assert list_tokens() == []

    # Generate token
    record, raw_token = generate_pat("Claude Desktop")
    assert record["name"] == "Claude Desktop"
    assert raw_token.startswith("ntb_")
    assert "token_hash" not in record

    # Listed tokens
    active = list_tokens()
    assert len(active) == 1
    assert active[0]["id"] == record["id"]
    assert active[0]["last_used_at"] is None

    # Validation
    assert not validate_token("invalid_token")
    assert not validate_token("")
    assert validate_token(raw_token)

    # Verify last_used_at was updated
    active = list_tokens()
    assert active[0]["last_used_at"] is not None

    # Revoke
    revoked = revoke_token(record["id"])
    assert revoked is True
    assert list_tokens() == []
    assert not validate_token(raw_token)
