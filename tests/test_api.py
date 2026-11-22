from datetime import datetime

from fastapi.testclient import TestClient

from tests.helpers import create_comment, create_post, login, sign_up


def assert_modified(before: dict, after: dict) -> None:
    assert after["created_at"] == before["created_at"]
    modified_at = datetime.fromisoformat(after["modified_at"])
    assert modified_at > datetime.fromisoformat(before["modified_at"])


def test_user_crud(client: TestClient):
    alice = sign_up(client)
    assert alice.user["username"] == "alice"
    assert alice.user["modified_at"] == alice.user["created_at"]

    assert client.get(f"/users/{alice.id}").json() == alice.user
    assert client.get("/users").json() == [alice.user]

    response = client.patch(
        f"/users/{alice.id}", json={"username": "alicia"}, headers=alice.headers
    )
    assert response.status_code == 200
    assert response.json()["username"] == "alicia"
    assert response.json()["email"] == "alice@example.com"
    assert_modified(alice.user, response.json())

    assert client.delete(f"/users/{alice.id}", headers=alice.headers).status_code == 204
    assert client.get(f"/users/{alice.id}").status_code == 404


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
        f"/users/{bob.id}", json={"email": "alice@example.com"}, headers=bob.headers
    )
    assert response.status_code == 409


def test_user_validation(client: TestClient):
    response = client.post(
        "/users",
        json={"username": "x", "email": "not-an-email", "password": "password123"},
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


def test_pagination(client: TestClient):
    users = [sign_up(client, f"user{i}").user for i in range(5)]

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
        f"/users/{alice.id}", json={"password": "a new password"}, headers=alice.headers
    )
    assert response.status_code == 200

    assert login(client, "alice", "a new password")
    response = client.post(
        "/auth/token",
        data={"username": "alice", "password": "correct horse battery staple"},
    )
    assert response.status_code == 401
