from fastapi.testclient import TestClient


def create_user(client: TestClient, username: str = "alice") -> dict:
    response = client.post(
        "/users", json={"username": username, "email": f"{username}@example.com"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_post(
    client: TestClient, user_id: int, title: str = "Hello", body: str = "First post"
) -> dict:
    response = client.post(
        "/posts", json={"title": title, "body": body, "user_id": user_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_comment(
    client: TestClient, post_id: int, user_id: int, body: str = "Nice"
) -> dict:
    response = client.post(
        "/comments", json={"body": body, "post_id": post_id, "user_id": user_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_crud(client: TestClient):
    user = create_user(client)
    assert user["username"] == "alice"

    assert client.get(f"/users/{user['id']}").json() == user
    assert client.get("/users").json() == [user]

    response = client.patch(f"/users/{user['id']}", json={"username": "alicia"})
    assert response.status_code == 200
    assert response.json()["username"] == "alicia"
    assert response.json()["email"] == "alice@example.com"

    assert client.delete(f"/users/{user['id']}").status_code == 204
    assert client.get(f"/users/{user['id']}").status_code == 404


def test_duplicate_user_conflicts(client: TestClient):
    create_user(client, "alice")
    bob = create_user(client, "bob")

    response = client.post(
        "/users", json={"username": "alice", "email": "other@example.com"}
    )
    assert response.status_code == 409

    response = client.patch(f"/users/{bob['id']}", json={"email": "alice@example.com"})
    assert response.status_code == 409


def test_user_validation(client: TestClient):
    response = client.post("/users", json={"username": "x", "email": "not-an-email"})
    assert response.status_code == 422


def test_user_has_many_posts(client: TestClient):
    alice = create_user(client, "alice")
    bob = create_user(client, "bob")
    p1 = create_post(client, alice["id"], "One")
    p2 = create_post(client, alice["id"], "Two")
    p3 = create_post(client, bob["id"], "Three")

    assert client.get(f"/users/{alice['id']}/posts").json() == [p1, p2]
    assert client.get(f"/users/{bob['id']}/posts").json() == [p3]
    assert client.get("/posts").json() == [p1, p2, p3]
    assert p1["user_id"] == alice["id"]


def test_post_crud(client: TestClient):
    user = create_user(client)
    post = create_post(client, user["id"])

    assert client.get(f"/posts/{post['id']}").json() == post

    response = client.patch(f"/posts/{post['id']}", json={"title": "Updated"})
    assert response.json()["title"] == "Updated"
    assert response.json()["body"] == "First post"

    assert client.delete(f"/posts/{post['id']}").status_code == 204
    assert client.get(f"/posts/{post['id']}").status_code == 404


def test_post_has_many_comments(client: TestClient):
    user = create_user(client)
    post = create_post(client, user["id"])
    other = create_post(client, user["id"], "Other")
    c1 = create_comment(client, post["id"], user["id"], "first")
    c2 = create_comment(client, post["id"], user["id"], "second")
    c3 = create_comment(client, other["id"], user["id"], "elsewhere")

    assert client.get(f"/posts/{post['id']}/comments").json() == [c1, c2]
    assert client.get(f"/posts/{other['id']}/comments").json() == [c3]
    assert client.get("/comments").json() == [c1, c2, c3]


def test_comment_crud(client: TestClient):
    user = create_user(client)
    post = create_post(client, user["id"])
    comment = create_comment(client, post["id"], user["id"])

    assert client.get(f"/comments/{comment['id']}").json() == comment

    response = client.patch(f"/comments/{comment['id']}", json={"body": "Edited"})
    assert response.json()["body"] == "Edited"

    assert client.delete(f"/comments/{comment['id']}").status_code == 204
    assert client.get(f"/comments/{comment['id']}").status_code == 404


def test_deleting_user_cascades_to_posts_and_comments(client: TestClient):
    user = create_user(client)
    post = create_post(client, user["id"])
    comment = create_comment(client, post["id"], user["id"])

    assert client.delete(f"/users/{user['id']}").status_code == 204
    assert client.get(f"/posts/{post['id']}").status_code == 404
    assert client.get(f"/comments/{comment['id']}").status_code == 404


def test_pagination(client: TestClient):
    users = [create_user(client, f"user{i}") for i in range(5)]

    assert client.get("/users", params={"offset": 1, "limit": 2}).json() == users[1:3]
    assert client.get("/users", params={"limit": 0}).status_code == 422


def test_comment_records_author(client: TestClient):
    alice = create_user(client, "alice")
    bob = create_user(client, "bob")
    post = create_post(client, alice["id"])
    by_bob = create_comment(client, post["id"], bob["id"], "from bob")
    by_alice = create_comment(client, post["id"], alice["id"], "from alice")

    assert by_bob["user_id"] == bob["id"]
    assert client.get(f"/users/{bob['id']}/comments").json() == [by_bob]
    assert client.get(f"/users/{alice['id']}/comments").json() == [by_alice]

    # The author can't be reassigned after the fact.
    response = client.patch(
        f"/comments/{by_bob['id']}", json={"body": "edited", "user_id": alice["id"]}
    )
    assert response.json()["user_id"] == bob["id"]


def test_post_requires_existing_author(client: TestClient):
    response = client.post("/posts", json={"title": "x", "body": "y"})
    assert response.status_code == 422

    response = client.post("/posts", json={"title": "x", "body": "y", "user_id": 999})
    assert response.status_code == 422
    assert response.json()["detail"] == "User not found"


def test_comment_requires_existing_post_and_author(client: TestClient):
    user = create_user(client)
    post = create_post(client, user["id"])

    for missing in ("post_id", "user_id"):
        body = {"body": "x", "post_id": post["id"], "user_id": user["id"]}
        del body[missing]
        assert client.post("/comments", json=body).status_code == 422

    response = client.post(
        "/comments", json={"body": "x", "post_id": 999, "user_id": user["id"]}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Post not found"

    response = client.post(
        "/comments", json={"body": "x", "post_id": post["id"], "user_id": 999}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "User not found"


def test_deleting_commenter_removes_their_comments(client: TestClient):
    alice = create_user(client, "alice")
    bob = create_user(client, "bob")
    post = create_post(client, alice["id"])
    by_alice = create_comment(client, post["id"], alice["id"])
    by_bob = create_comment(client, post["id"], bob["id"])

    assert client.delete(f"/users/{bob['id']}").status_code == 204
    assert client.get(f"/posts/{post['id']}/comments").json() == [by_alice]
    assert client.get(f"/comments/{by_bob['id']}").status_code == 404
