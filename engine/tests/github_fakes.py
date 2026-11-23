"""Block 08 test doubles: a freshly generated RSA key (never the real app's) and a small fake GitHub API on a local port.
The fake checks every app JWT with the test key's public half, hands out ghs_ installation tokens and pages /installation/repositories."""
import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Body, FastAPI, Header, Request
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
    st = SimpleNamespace(installs={}, tokens={}, token_calls=0, jwts=[], fail=None, clock=time.time, token_requests=[], scope={}, repos={}, writes=[])
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
    def access_token(iid: int, authorization: str | None = Header(None), body: dict | None = Body(None)):
        if not app_claims(authorization):
            return refuse(401)
        st.token_requests.append(body)
        if st.fail:
            return refuse(st.fail, "Resource not accessible by integration")
        if iid not in st.installs:
            return refuse(404, "Not Found")
        st.token_calls += 1
        token = "ghs_" + secrets.token_hex(18)
        st.tokens[token] = iid
        st.scope[token] = body  # None: a plain read token. A body: what the downscoped token was limited to
        return JSONResponse({"token": token, "expires_at": datetime.fromtimestamp(st.clock() + 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, 201)

    @app.get("/installation/repositories")
    def repositories(request: Request, per_page: int = 30, page: int = 1, authorization: str | None = Header(None)):
        iid = st.tokens.get((authorization or "").removeprefix("Bearer "))
        if iid is None:
            return refuse(401)
        names = st.installs[iid]["repos"]
        chunk = names[(page - 1) * per_page: page * per_page]
        return {"total_count": len(names), "repositories": [{"full_name": n, "private": True, "default_branch": "main"} for n in chunk]}

    # ---- a small git data API for the pull request flow. Only POSTs that add objects, a NEW ref and a pull request exist: there is no
    # route to move a ref, delete one or merge, so a test that passes proves none of that was attempted (st.writes lists every write).

    def write_auth(authorization, owner, name):
        token = (authorization or "").removeprefix("Bearer ")
        scope = st.scope.get(token)
        if token not in st.tokens:
            return refuse(401)
        if not scope or scope.get("repositories") != [name] or scope.get("permissions") != {"contents": "write", "pull_requests": "write"}:
            return refuse(403, "Resource not accessible by integration")  # a plain read token, or a token for other repositories
        if f"{owner}/{name}" not in st.repos:
            return refuse(404, "Not Found")
        return None

    def repo_of(owner, name):
        return st.repos[f"{owner}/{name}"]

    @app.get("/repos/{owner}/{name}")
    def get_repo(owner: str, name: str, authorization: str | None = Header(None)):
        return write_auth(authorization, owner, name) or {"default_branch": repo_of(owner, name)["default"]}

    @app.get("/repos/{owner}/{name}/git/ref/heads/{branch:path}")
    def get_ref(owner: str, name: str, branch: str, authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        sha = None if denied else repo_of(owner, name)["refs"].get(branch)
        return denied or (refuse(404, "Not Found") if sha is None else {"object": {"sha": sha}})

    @app.get("/repos/{owner}/{name}/git/commits/{sha}")
    def get_commit(owner: str, name: str, sha: str, authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        c = None if denied else repo_of(owner, name)["commits"].get(sha)
        return denied or (refuse(404, "Not Found") if c is None else {"tree": {"sha": c["tree"]}})

    @app.get("/repos/{owner}/{name}/git/trees/{sha}")
    def get_tree(owner: str, name: str, sha: str, authorization: str | None = Header(None)):
        return write_auth(authorization, owner, name) or {"tree": repo_of(owner, name)["trees"][sha], "truncated": False}

    @app.get("/repos/{owner}/{name}/git/blobs/{sha}")
    def get_blob(owner: str, name: str, sha: str, authorization: str | None = Header(None)):
        return write_auth(authorization, owner, name) or {"content": base64.b64encode(repo_of(owner, name)["blobs"][sha]).decode(), "encoding": "base64"}

    @app.post("/repos/{owner}/{name}/git/blobs", status_code=201)
    def post_blob(owner: str, name: str, body: dict = Body(...), authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        if denied:
            return denied
        data = body["content"].encode()
        sha = hashlib.sha1(b"blob " + data).hexdigest()
        repo_of(owner, name)["blobs"][sha] = data
        st.writes.append(("POST", "git/blobs", body))
        return {"sha": sha}

    @app.post("/repos/{owner}/{name}/git/trees", status_code=201)
    def post_tree(owner: str, name: str, body: dict = Body(...), authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        if denied:
            return denied
        r = repo_of(owner, name)
        entries = {e["path"]: e for e in r["trees"][body["base_tree"]]}
        entries.update({e["path"]: e for e in body["tree"]})
        sha = hashlib.sha1(json.dumps(sorted(entries), sort_keys=True).encode() + json.dumps([entries[k]["sha"] for k in sorted(entries)]).encode()).hexdigest()
        r["trees"][sha] = list(entries.values())
        st.writes.append(("POST", "git/trees", body))
        return {"sha": sha}

    @app.post("/repos/{owner}/{name}/git/commits", status_code=201)
    def post_commit(owner: str, name: str, body: dict = Body(...), authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        if denied:
            return denied
        sha = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()
        repo_of(owner, name)["commits"][sha] = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}
        st.writes.append(("POST", "git/commits", body))
        return {"sha": sha}

    @app.post("/repos/{owner}/{name}/git/refs", status_code=201)
    def post_ref(owner: str, name: str, body: dict = Body(...), authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        if denied:
            return denied
        r, branch = repo_of(owner, name), body["ref"].removeprefix("refs/heads/")
        if branch in r["refs"]:
            return refuse(422, "Reference already exists")
        r["refs"][branch] = body["sha"]
        st.writes.append(("POST", "git/refs", body))
        return {"ref": body["ref"]}

    @app.get("/repos/{owner}/{name}/pulls")
    def list_pulls(owner: str, name: str, head: str = "", state: str = "open", authorization: str | None = Header(None)):
        return write_auth(authorization, owner, name) or [p for p in repo_of(owner, name)["prs"] if f"{owner}:{p['head']}" == head and p["state"] == state]

    @app.post("/repos/{owner}/{name}/pulls", status_code=201)
    def post_pull(owner: str, name: str, body: dict = Body(...), authorization: str | None = Header(None)):
        denied = write_auth(authorization, owner, name)
        if denied:
            return denied
        r = repo_of(owner, name)
        if body["head"] not in r["refs"] or body["base"] != r["default"]:
            return refuse(422, "Validation Failed")
        pr = {"number": len(r["prs"]) + 1, "head": body["head"], "state": "open", "title": body["title"], "body": body["body"], "base": body["base"],
              "html_url": f"https://github.com/{owner}/{name}/pull/{len(r['prs']) + 1}"}
        r["prs"].append(pr)
        st.writes.append(("POST", "pulls", body))
        return pr

    return app, st


def add_repo(st, full_name: str, files: dict[str, str], default: str = "main", modes: dict | None = None, commit: str | None = None) -> str:
    """A repository in the fake GitHub with one commit holding `files`. Returns the commit sha."""
    blobs, entries = {}, []
    for path, text in files.items():
        data = text.encode()
        sha = hashlib.sha1(b"blob " + data).hexdigest()
        blobs[sha] = data
        entries.append({"path": path, "mode": (modes or {}).get(path, "100644"), "type": "blob", "sha": sha})
    tree = hashlib.sha1(json.dumps(sorted(files)).encode()).hexdigest()
    commit = commit or hashlib.sha1(json.dumps([full_name, sorted(files)]).encode()).hexdigest()
    st.repos[full_name] = {"default": default, "refs": {default: commit}, "commits": {commit: {"tree": tree, "parents": []}}, "trees": {tree: entries},
                           "blobs": blobs, "prs": []}
    return commit
