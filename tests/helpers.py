from dataclasses import dataclass

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


@dataclass
class Account:
    """A signed-up user and the headers that authenticate as them."""

    user: dict
    headers: dict[str, str]

    @property
    def id(self) -> int:
        return self.user["id"]


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    response = client.post(
        "/auth/token", data={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def sign_up(client: TestClient, username: str = "alice") -> Account:
    response = client.post(
        "/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return Account(response.json(), login(client, username))


def create_post(client: TestClient, author: Account, body: str = "First post") -> dict:
    response = client.post("/posts", json={"body": body}, headers=author.headers)
    assert response.status_code == 201, response.text
    return response.json()


def create_comment(
    client: TestClient, author: Account, post_id: int, body: str = "Nice"
) -> dict:
    response = client.post(
        "/comments", json={"body": body, "post_id": post_id}, headers=author.headers
    )
    assert response.status_code == 201, response.text
    return response.json()
