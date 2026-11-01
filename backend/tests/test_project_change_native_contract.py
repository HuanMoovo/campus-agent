"""Real API/COW results must pass the actual Electron response validators."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest
from test_project_change_api import change_client, proposal, prepare, commit, BEFORE, AFTER


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Production editing is Windows NTFS only")


def test_native_policy_accepts_real_apply_undo_keep_and_recovery_payloads(change_client):
    node = os.environ.get("CAMPUS_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node runtime is required for the native response contract")
    client, folder, project_id, _ = change_client
    exchanges = []
    for final_action in ("revert", "keep"):
        draft = proposal(client, project_id)
        prepared = prepare(client, project_id, draft["id"]).json()
        operation_id = str(uuid4())
        response = commit(client, project_id, draft["id"], prepared["digest"], operation_id=operation_id)
        assert response.status_code == 200, response.text
        applied = response.json()
        assert applied["state"] == "applied"
        assert (folder / "README.md").read_bytes() == AFTER
        exchanges.append({"prepared": prepared, "receipt": applied})
        result = client.get(f"/api/projects/{project_id}/changes/operations/{operation_id}")
        assert result.status_code == 200
        assert result.json()["operation_id"] == operation_id
        prepared = prepare(client, project_id, applied["recovery_id"], final_action).json()
        response = commit(client, project_id, applied["recovery_id"], prepared["digest"], final_action)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == ("reverted" if final_action == "revert" else "kept")
        exchanges.append({"prepared": prepared, "receipt": response.json()})
        assert (folder / "README.md").read_bytes() == (BEFORE if final_action == "revert" else AFTER)
    listing = client.get(f"/api/projects/{project_id}/changes").json()
    original = client.get(f"/api/projects/{project_id}/changes/{applied['recovery_id']}/original").json()
    policy = Path(__file__).resolve().parents[2] / "desktop" / "lib" / "policy.cjs"
    script = r"""
const fs = require('node:fs');
const policy = require(process.argv[1]);
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const item of data.exchanges) {
  const value = item.prepared;
  policy.validateProjectChangePreparation(value, {projectId:value.project_id, subjectId:value.subject_id, action:value.action});
  policy.validateProjectChangeReceipt(item.receipt, {project_id:value.project_id, subject_id:value.subject_id, action:value.action, digest:value.digest});
  if ('digest' in policy.projectChangePublicReceipt(item.receipt)) throw new Error('private field exposed');
}
policy.validateProjectChangeList(data.listing, data.project_id);
policy.validateProjectRecoveryOriginal(data.original);
process.stdout.write('native-contract-ok');
"""
    result = subprocess.run([node, "-e", script, str(policy)],
                            input=json.dumps({"exchanges": exchanges, "listing": listing,
                                              "original": original, "project_id": project_id}),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "native-contract-ok"
