"""Block 08 test doubles: a freshly generated RSA key (never the real app's) and a small fake GitHub API on a local port.
The fake checks every app JWT with the test key's public half, hands out ghs_ installation tokens and pages /installation/repositories."""
import secrets
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

APP_ID = "424242"
SLUG = "dpdp-test"


def make_key(path, mode: int = 0o600) -> str:
    """Write a new test private key to `path` with `mode`. Returns the PEM of its public half."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    path.chmod(mode)
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def make_github(public_pem: str):
    """Returns (app, state). state.installs: {id: {"login", "type", "repos": [full names]}}. state.token_calls counts token exchanges,
    state.tokens maps each token handed out to its installation id, state.jwts keeps the decoded claims of every app JWT it accepted.
    state.fail: a status code to answer on the token exchange (None for normal). state.clock decides token expiry."""
    st = SimpleNamespace(installs={}, tokens={}, token_calls=0, jwts=[], fail=None, clock=time.time)
    app = FastAPI()

    def refuse(status, message="Bad credentials"):
        return JSONResponse({"message": message}, status_code=status)

    def app_claims(authorization):
        try:  # leeway: tests move the app's clock an hour ahead, and the fake still has to accept that JWT
            claims = jwt.decode((authorization or "").removeprefix("Bearer "), public_pem, algorithms=["RS256"], issuer=APP_ID, leeway=7200,
                                options={"require": ["iat", "exp", "iss"]})
        except jwt.PyJWTError:
            return None
        st.jwts.append(claims)
        return claims

    @app.get("/app")
    def get_app(authorization: str | None = Header(None)):
        return {"slug": SLUG, "id": int(APP_ID)} if app_claims(authorization) else refuse(401)

    @app.get("/app/installations/{iid}")
    def get_installation(iid: int, authorization: str | None = Header(None)):
        if not app_claims(authorization):
            return refuse(401)
        i = st.installs.get(iid)
        return {"id": iid, "account": {"login": i["login"], "type": i["type"]}} if i else refuse(404, "Not Found")

    @app.post("/app/installations/{iid}/access_tokens")
    def access_token(iid: int, authorization: str | None = Header(None)):
        if not app_claims(authorization):
            return refuse(401)
        if st.fail:
            return refuse(st.fail, "Resource not accessible by integration")
        if iid not in st.installs:
            return refuse(404, "Not Found")
        st.token_calls += 1
        token = "ghs_" + secrets.token_hex(18)
        st.tokens[token] = iid
        return JSONResponse({"token": token, "expires_at": datetime.fromtimestamp(st.clock() + 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, 201)

    @app.get("/installation/repositories")
    def repositories(request: Request, per_page: int = 30, page: int = 1, authorization: str | None = Header(None)):
        iid = st.tokens.get((authorization or "").removeprefix("Bearer "))
        if iid is None:
            return refuse(401)
        names = st.installs[iid]["repos"]
        chunk = names[(page - 1) * per_page: page * per_page]
        return {"total_count": len(names), "repositories": [{"full_name": n, "private": True, "default_branch": "main"} for n in chunk]}

    return app, st
