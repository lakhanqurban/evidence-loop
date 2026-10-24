from typing import Optional

from fastapi import FastAPI, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.testclient import TestClient


def test_non_bearer_scheme_is_absent_when_authentication_is_optional():
    app = FastAPI()
    security = HTTPBearer(auto_error=False)

    @app.get("/users/me")
    def read_current_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    ):
        if credentials is None:
            return {"msg": "Create an account first"}
        return {"scheme": credentials.scheme, "credentials": credentials.credentials}

    response = TestClient(app).get(
        "/users/me",
        headers={"Authorization": "Basic notreally"},
    )

    assert response.status_code == 200
    assert response.json() == {"msg": "Create an account first"}