"""Actual archive/project API payloads must pass the actual native read policy."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app import project_api
from app.project_recovery_backup import ProjectRecoveryArchive, export_materials
from test_project_change_api import AFTER, BEFORE, applied, change_client, commit, prepare

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Synthetic production editing requires Windows NTFS")


def test_imported_originals_pass_native_policy_without_restoring_write_authority(change_client, monkeypatch):
    node = os.environ.get("CAMPUS_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node is required for the native protocol contract")
    client, folder, project_id, data_dir = change_client
    applied(client, project_id)
    journal = data_dir / "project-changes.sqlite3"
    journal_before = journal.read_bytes()
    archive = ProjectRecoveryArchive(data_dir)
    assert archive.insert(export_materials(data_dir)) == {"imported": 1, "duplicates": 0}
    monkeypatch.setattr(project_api, "archives", archive)
    response = client.get(f"/api/projects/{project_id}/changes")
    assert response.status_code == 200, response.text
    listing = response.json()
    assert len(listing["records"]) == len(listing["archives"]) == 1
    archive_id = listing["archives"][0]["archive_id"]
    response = client.get(f"/api/projects/{project_id}/changes/{archive_id}/original")
    assert response.status_code == 200, response.text
    original = response.json()
    assert original == {"text": BEFORE.decode("utf-8-sig"), "bom": True, "newline": "crlf"}
    assert prepare(client, project_id, archive_id, "revert").status_code == 422
    assert commit(client, project_id, archive_id, "d" * 64, "revert").status_code == 422
    assert journal.read_bytes() == journal_before
    assert (folder / "README.md").read_bytes() == AFTER
    policy = Path(__file__).resolve().parents[2] / "desktop" / "lib" / "policy.cjs"
    script = r"""
const fs = require('node:fs');
const policy = require(process.argv[1]);
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const list = policy.validateProjectChangeList(data.listing, data.project_id);
if (list.archives.length !== 1 || Object.keys(list.archives[0]).length !== 5) throw new Error('invalid archive surface');
policy.validateProjectRecoveryOriginal(data.original);
process.stdout.write('archive-native-contract-ok');
"""
    result = subprocess.run([node, "-e", script, str(policy)],
                            input=json.dumps({"listing": listing, "project_id": project_id, "original": original}),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "archive-native-contract-ok"
