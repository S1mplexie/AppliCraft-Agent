"""申请项目：知识库导入 / 自定义新建、文书归组与项目过滤。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import init_db
from app.library.service import list_system_programs
from app.main import app
from app.storage.filestore import FileStore

PASSWORD = "test-password-123"


def setup_module():
    app.dependency_overrides.clear()
    init_db()


def teardown_module():
    app.dependency_overrides.clear()


def _client() -> TestClient:
    c = TestClient(app)
    email = f"proj_{uuid4().hex[:10]}@example.com"
    resp = c.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return c


def _profile_id(client: TestClient, label: str = "项目档案") -> str:
    return client.post("/api/profiles", json={"label": label}).json()["id"]


def _user_id(client: TestClient) -> str:
    return client.get("/api/auth/me").json()["user"]["id"]


def _seed_document(user_id: str, profile_id: str) -> str:
    """直接用存储层预置一篇文书，绕过完整生成工作流。"""
    store = FileStore(get_settings().data_dir).for_user(user_id)
    meta = store.save_document(
        profile_id=profile_id,
        doc_type="ps",
        markdown="测试文书正文。",
        trace={},
        model="stub",
        language="zh",
    )
    return meta["id"]


def test_create_custom_project():
    client = _client()
    pid = _profile_id(client)
    resp = client.post(f"/api/profiles/{pid}/projects", json={
        "name": "港大 CS 备选", "university": "香港大学", "program": "计算机科学",
        "degree_type": "MSc", "region": "HK", "intake": "2027 FALL",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source"] == "custom"
    assert data["university"] == "香港大学"
    assert data["profile_id"] == pid
    items = client.get(f"/api/profiles/{pid}/projects").json()["items"]
    assert items[0]["document_count"] == 0


def test_import_from_system_programs():
    client = _client()
    pid = _profile_id(client)
    programs = list_system_programs(get_settings())
    assert programs, "知识库项目列表不应为空"
    target = programs[0]
    resp = client.post(f"/api/profiles/{pid}/projects", json={
        "name": f"{target['school_name_zh']}导入", "system_program_id": target["program_id"],
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source"] == "imported"
    assert data["system_program_id"] == target["program_id"]
    # 官方字段被快照填充，不依赖用户手动填写
    assert data["university"] == target["school_name_zh"]
    assert data["program"] == target["program_name_zh"]
    assert data["region"] == target["region"]


def test_import_404_for_unknown_program():
    client = _client()
    pid = _profile_id(client)
    resp = client.post(f"/api/profiles/{pid}/projects", json={
        "name": "不存在的项目", "system_program_id": "no-such-program",
    })
    assert resp.status_code == 404


def test_list_scoped_by_profile():
    client = _client()
    pid_a = _profile_id(client, "档案A")
    pid_b = _profile_id(client, "档案B")
    assert client.post(f"/api/profiles/{pid_a}/projects", json={"name": "A 的项目"}).status_code == 201
    assert client.post(f"/api/profiles/{pid_b}/projects", json={"name": "B 的项目"}).status_code == 201
    names_a = [x["name"] for x in client.get(f"/api/profiles/{pid_a}/projects").json()["items"]]
    names_b = [x["name"] for x in client.get(f"/api/profiles/{pid_b}/projects").json()["items"]]
    assert names_a == ["A 的项目"]
    assert names_b == ["B 的项目"]


def test_assign_filter_and_ungrouped():
    client = _client()
    uid = _user_id(client)
    pid = _profile_id(client)
    proj = client.post(f"/api/profiles/{pid}/projects", json={"name": "归组项目"}).json()
    doc_a = _seed_document(uid, pid)
    doc_b = _seed_document(uid, pid)

    resp = client.post(f"/api/profiles/{pid}/projects/{proj['id']}/assign",
                       json={"doc_id": doc_a})
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == proj["id"]

    in_project = client.get("/api/documents", params={"profile_id": pid, "project_id": proj["id"]}).json()["items"]
    ungrouped = client.get("/api/documents", params={"profile_id": pid, "project_id": "ungrouped"}).json()["items"]
    all_docs = client.get("/api/documents", params={"profile_id": pid}).json()["items"]
    assert [d["id"] for d in in_project] == [doc_a]
    assert sorted(d["id"] for d in ungrouped) == sorted([doc_b])
    assert len(all_docs) == 2


def test_unassign_back_to_ungrouped():
    client = _client()
    uid = _user_id(client)
    pid = _profile_id(client)
    proj = client.post(f"/api/profiles/{pid}/projects", json={"name": "移出项目"}).json()
    doc_id = _seed_document(uid, pid)
    assert client.post(f"/api/profiles/{pid}/projects/{proj['id']}/assign",
                       json={"doc_id": doc_id}).status_code == 200
    resp = client.post(f"/api/profiles/{pid}/projects/{proj['id']}/unassign",
                       json={"doc_id": doc_id})
    assert resp.status_code == 200, resp.text
    assert "project_id" not in resp.json()
    ungrouped = client.get("/api/documents", params={"profile_id": pid, "project_id": "ungrouped"}).json()["items"]
    assert doc_id in [d["id"] for d in ungrouped]


def test_delete_project_keeps_documents_ungrouped():
    client = _client()
    uid = _user_id(client)
    pid = _profile_id(client)
    proj = client.post(f"/api/profiles/{pid}/projects", json={"name": "待删除"}).json()
    doc_id = _seed_document(uid, pid)
    assert client.post(f"/api/profiles/{pid}/projects/{proj['id']}/assign",
                       json={"doc_id": doc_id}).status_code == 200

    assert client.delete(f"/api/profiles/{pid}/projects/{proj['id']}").status_code == 200
    # 项目没了，但文书保留并回到未分组
    all_docs = client.get("/api/documents", params={"profile_id": pid}).json()["items"]
    assert doc_id in [d["id"] for d in all_docs]
    assert all(d.get("project_id") is None for d in all_docs)



def test_404_for_missing_profile():
    client = _client()
    resp = client.get("/api/profiles/nonexistent/projects")
    assert resp.status_code == 404


def test_assign_404_for_foreign_document():
    client = _client()
    uid = _user_id(client)
    pid_a = _profile_id(client, "档案A")
    pid_b = _profile_id(client, "档案B")
    proj_b = client.post(f"/api/profiles/{pid_b}/projects", json={"name": "B 项目"}).json()
    doc_a = _seed_document(uid, pid_a)
    # 档案 A 的文书不能归入档案 B 的项目
    resp = client.post(f"/api/profiles/{pid_b}/projects/{proj_b['id']}/assign",
                       json={"doc_id": doc_a})
    assert resp.status_code == 404


def test_requires_login():
    client = TestClient(app)
    resp = client.get("/api/profiles/whatever/projects")
    assert resp.status_code == 401