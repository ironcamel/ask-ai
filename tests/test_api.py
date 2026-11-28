from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from ask_ai.models import MAX_BODY_LENGTH
from tests.helpers import (
    PASSWORD,
    Account,
    create_comment,
    create_post,
    login,
    sign_up,
)


def assert_modified(before: dict, after: dict) -> None:
    assert after["created_at"] == before["created_at"]
    modified_at = datetime.fromisoformat(after["modified_at"])
    assert modified_at > datetime.fromisoformat(before["modified_at"])


def test_user_crud(client: TestClient):
    alice = sign_up(client)
    assert alice.user["username"] == "alice"
    assert alice.user["modified_at"] == alice.user["created_at"]

    assert alice.user["email"] == "alice@example.com"
    assert client.get(f"/users/{alice.id}").json() == alice.public
    assert client.get("/users").json() == [alice.public]

    response = client.patch(
        f"/users/{alice.id}", json={"username": "alicia"}, headers=alice.headers
    )
    assert response.status_code == 200
    assert response.json()["username"] == "alicia"
    assert response.json()["email"] == "alice@example.com"
    assert_modified(alice.user, response.json())

    assert client.delete(f"/users/{alice.id}", headers=alice.headers).status_code == 204
    assert client.get(f"/users/{alice.id}").status_code == 404


def test_email_is_seen_only_by_its_owner(client: TestClient):
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")

    for headers in [{}, bob.headers, alice.headers]:
        assert "email" not in client.get(f"/users/{alice.id}", headers=headers).json()
        users = client.get("/users", headers=headers).json()
        assert all("email" not in user for user in users)
    me = client.get("/users/me", headers=alice.headers).json()
    assert me["email"] == "alice@example.com"


def test_duplicate_user_conflicts(client: TestClient):
    sign_up(client, "alice")
    bob = sign_up(client, "bob")

    response = client.post(
        "/users",
        json={
            "username": "alice",
            "email": "other@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 409

    response = client.patch(
        f"/users/{bob.id}",
        json={"email": "alice@example.com", "current_password": PASSWORD},
        headers=bob.headers,
    )
    assert response.status_code == 409


def test_user_validation(client: TestClient):
    response = client.post(
        "/users",
        json={"username": "x", "email": "not-an-email", "password": "password123"},
    )
    assert response.status_code == 422


def test_username_is_lowercased(client: TestClient):
    response = client.post(
        "/users",
        json={
            "username": "Alice_42",
            "email": "alice@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    assert response.json()["username"] == "alice_42"
    alice = Account(response.json(), login(client, "alice_42"))

    response = client.patch(
        f"/users/{alice.id}", json={"username": "ALICIA"}, headers=alice.headers
    )
    assert response.status_code == 200
    assert response.json()["username"] == "alicia"


def test_usernames_differing_in_case_conflict(client: TestClient):
    sign_up(client, "alice")
    response = client.post(
        "/users",
        json={"username": "ALICE", "email": "x@example.com", "password": PASSWORD},
    )
    assert response.status_code == 409


# "K" is the Kelvin sign, which lowercases to an ASCII "k".
@pytest.mark.parametrize(
    "username", ["", "al ice", "al-ice", "al.ice", "zoë", "名前", "Kate", "x" * 51]
)
def test_username_must_be_ascii_word_characters(client: TestClient, username: str):
    response = client.post(
        "/users",
        json={"username": username, "email": "x@example.com", "password": PASSWORD},
    )
    assert response.status_code == 422

    bob = sign_up(client, "bob")
    response = client.patch(
        f"/users/{bob.id}", json={"username": username}, headers=bob.headers
    )
    assert response.status_code == 422


def test_user_has_many_posts(client: TestClient):
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")
    p1 = create_post(client, alice, "One")
    p2 = create_post(client, alice, "Two")
    p3 = create_post(client, bob, "Three")

    assert client.get(f"/users/{alice.id}/posts").json() == [p1, p2]
    assert client.get(f"/users/{bob.id}/posts").json() == [p3]
    assert client.get("/posts").json() == [p1, p2, p3]
    assert p1["user_id"] == alice.id


def test_post_crud(client: TestClient):
    alice = sign_up(client)
    post = create_post(client, alice)
    assert post["modified_at"] == post["created_at"]

    assert client.get(f"/posts/{post['id']}").json() == post

    response = client.patch(
        f"/posts/{post['id']}", json={"body": "Updated"}, headers=alice.headers
    )
    assert response.json()["body"] == "Updated"
    assert response.json()["user_id"] == alice.id
    assert_modified(post, response.json())

    response = client.delete(f"/posts/{post['id']}", headers=alice.headers)
    assert response.status_code == 204
    assert client.get(f"/posts/{post['id']}").status_code == 404


def test_post_has_many_comments(client: TestClient):
    alice = sign_up(client)
    post = create_post(client, alice)
    other = create_post(client, alice, "Other")
    c1 = create_comment(client, alice, post["id"], "first")
    c2 = create_comment(client, alice, post["id"], "second")
    c3 = create_comment(client, alice, other["id"], "elsewhere")

    assert client.get(f"/posts/{post['id']}/comments").json() == [c1, c2]
    assert client.get(f"/posts/{other['id']}/comments").json() == [c3]
    assert client.get("/comments").json() == [c1, c2, c3]


def test_comment_crud(client: TestClient):
    alice = sign_up(client)
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"])
    assert comment["modified_at"] == comment["created_at"]

    assert client.get(f"/comments/{comment['id']}").json() == comment

    response = client.patch(
        f"/comments/{comment['id']}", json={"body": "Edited"}, headers=alice.headers
    )
    assert response.json()["body"] == "Edited"
    assert_modified(comment, response.json())

    response = client.delete(f"/comments/{comment['id']}", headers=alice.headers)
    assert response.status_code == 204
    assert client.get(f"/comments/{comment['id']}").status_code == 404


def test_deleting_user_cascades_to_posts_and_comments(client: TestClient):
    alice = sign_up(client)
    post = create_post(client, alice)
    comment = create_comment(client, alice, post["id"])

    assert client.delete(f"/users/{alice.id}", headers=alice.headers).status_code == 204
    assert client.get(f"/posts/{post['id']}").status_code == 404
    assert client.get(f"/comments/{comment['id']}").status_code == 404


def test_body_length_is_limited(client: TestClient):
    alice = sign_up(client)
    longest, too_long = "x" * MAX_BODY_LENGTH, "x" * (MAX_BODY_LENGTH + 1)
    post = create_post(client, alice, longest)
    comment = create_comment(client, alice, post["id"], longest)

    for method, path, body in [
        ("POST", "/posts", {"body": too_long}),
        ("PATCH", f"/posts/{post['id']}", {"body": too_long}),
        ("POST", "/comments", {"post_id": post["id"], "body": too_long}),
        ("PATCH", f"/comments/{comment['id']}", {"body": too_long}),
    ]:
        response = client.request(method, path, json=body, headers=alice.headers)
        assert response.status_code == 422, (method, path)


def test_pagination(client: TestClient):
    users = [sign_up(client, f"user{i}").public for i in range(5)]

    assert client.get("/users", params={"offset": 1, "limit": 2}).json() == users[1:3]
    assert client.get("/users", params={"limit": 0}).status_code == 422


def test_comment_records_author(client: TestClient):
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")
    post = create_post(client, alice)
    by_bob = create_comment(client, bob, post["id"], "from bob")
    by_alice = create_comment(client, alice, post["id"], "from alice")

    assert by_bob["user_id"] == bob.id
    assert client.get(f"/users/{bob.id}/comments").json() == [by_bob]
    assert client.get(f"/users/{alice.id}/comments").json() == [by_alice]

    # The author can't be reassigned after the fact.
    response = client.patch(
        f"/comments/{by_bob['id']}",
        json={"body": "edited", "user_id": alice.id},
        headers=bob.headers,
    )
    assert response.json()["user_id"] == bob.id


def test_author_comes_from_token_not_body(client: TestClient):
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")

    response = client.post(
        "/posts", json={"body": "hi", "user_id": bob.id}, headers=alice.headers
    )
    post = response.json()
    assert post["user_id"] == alice.id

    response = client.post(
        "/comments",
        json={"body": "hi", "post_id": post["id"], "user_id": bob.id},
        headers=alice.headers,
    )
    assert response.json()["user_id"] == alice.id


def test_comment_requires_existing_post(client: TestClient):
    alice = sign_up(client)

    response = client.post("/comments", json={"body": "x"}, headers=alice.headers)
    assert response.status_code == 422

    response = client.post(
        "/comments", json={"body": "x", "post_id": 999}, headers=alice.headers
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Post not found"


def test_deleting_commenter_removes_their_comments(client: TestClient):
    alice = sign_up(client, "alice")
    bob = sign_up(client, "bob")
    post = create_post(client, alice)
    by_alice = create_comment(client, alice, post["id"])
    by_bob = create_comment(client, bob, post["id"])

    assert client.delete(f"/users/{bob.id}", headers=bob.headers).status_code == 204
    assert client.get(f"/posts/{post['id']}/comments").json() == [by_alice]
    assert client.get(f"/comments/{by_bob['id']}").status_code == 404


def test_password_change(client: TestClient):
    alice = sign_up(client)

    response = client.patch(
        f"/users/{alice.id}",
        json={"password": "a new password", "current_password": PASSWORD},
        headers=alice.headers,
    )
    assert response.status_code == 200

    assert login(client, "alice", "a new password")
    response = client.post(
        "/auth/token", data={"username": "alice", "password": PASSWORD}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "change", [{"email": "mallory@example.com"}, {"password": "mallory's password"}]
)
@pytest.mark.parametrize("current_password", [None, "wrong password"])
def test_email_and_password_changes_need_current_password(
    client: TestClient, change: dict, current_password: str | None
):
    alice = sign_up(client)
    body = change | ({"current_password": current_password} if current_password else {})

    response = client.patch(f"/users/{alice.id}", json=body, headers=alice.headers)
    assert response.status_code == 403
    me = client.get("/users/me", headers=alice.headers).json()
    assert me["email"] == "alice@example.com"
    assert login(client, "alice", PASSWORD)
