"""Publish the campus-agent repository to GitHub through the REST API.

git push does not work from this machine (direct 443 blocked / proxy resets TLS), so the
whole tree is uploaded with the Git Data API: blobs -> tree -> commit -> ref update.
Run:  python publish_github.py --token-file <path> [--repo campus-agent] [--dry-run]
"""
import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API = 'https://api.github.com'
OWNER = 'HuanMoovo'
REPO = 'campus-agent'
DESCRIPTION = 'Mens 校园助手 — 本地优先的校园问答工作台（Electron + Vue 3 + FastAPI）：知识库检索、校园服务、流式问答与可选联网搜索；Windows/macOS/Linux 构建，移动端可安装网页版。'


def call(method: str, path: str, token: str, payload=None, *, raw=False, retries=3):
    url = path if path.startswith('http') else API + path
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    for attempt in range(1, retries + 1):
        request = Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json',
        })
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
                return body if raw else (json.loads(body) if body else None)
        except HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:400]
            if error.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 * attempt)
                continue
            raise RuntimeError(f'{method} {url} -> {error.code}: {detail}') from error
    raise RuntimeError('unreachable')


def tracked_files() -> list[Path]:
    output = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
    names = [name for name in output.decode('utf-8').split('\0') if name]
    if not names:
        raise SystemExit('git ls-files returned nothing — commit the work first.')
    return [ROOT / name for name in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--repo', default=REPO)
    parser.add_argument('--owner', default=OWNER)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    token = Path(args.token_file).read_text(encoding='utf-8').strip()
    repo_path = f'/repos/{args.owner}/{args.repo}'

    files = tracked_files()
    total = sum(path.stat().st_size for path in files)
    print(f'files: {len(files)} | bytes: {total:,}')

    existing = None
    try:
        existing = call('GET', repo_path, token)
    except RuntimeError as error:
        if '-> 404' not in str(error):
            raise
    if existing is None:
        if args.dry_run:
            print('dry-run: repository would be created')
            return
        created = call('POST', f'/user/repos', token, {
            'name': args.repo, 'description': DESCRIPTION, 'private': False,
            'has_issues': True, 'has_wiki': False, 'has_projects': False, 'auto_init': True,
        })
        print('created repository:', created['html_url'])
        branch = created.get('default_branch', 'main')
    else:
        branch = existing.get('default_branch', 'main')
        if not args.dry_run:
            call('PATCH', repo_path, token, {'description': DESCRIPTION})
        print('repository exists:', existing['html_url'], '| branch:', branch)

    if args.dry_run:
        print('dry-run: skipping upload')
        return

    blobs = {}
    for index, path in enumerate(files, start=1):
        relative = path.relative_to(ROOT).as_posix()
        content = base64.b64encode(path.read_bytes()).decode('ascii')
        result = call('POST', f'{repo_path}/git/blobs', token, {'content': content, 'encoding': 'base64'})
        blobs[relative] = result['sha']
        if index % 20 == 0 or index == len(files):
            print(f'  uploaded {index}/{len(files)} blobs')

    head = call('GET', f'{repo_path}/git/ref/heads/{branch}', token)
    parent = head['object']['sha']
    parent_commit = call('GET', f'{repo_path}/git/commits/{parent}', token)

    tree = call('POST', f'{repo_path}/git/trees', token, {
        'base_tree': parent_commit['tree']['sha'],
        'tree': [{'path': name, 'mode': '100755' if name.endswith(('.sh',)) else '100644',
                  'type': 'blob', 'sha': sha} for name, sha in blobs.items()],
    })
    commit = call('POST', f'{repo_path}/git/commits', token, {
        'message': 'Mens 1.2.0：联网搜索、跨平台构建与可安装网页版\n\n'
                   '同步开发副本的全部改动：流式回答与停止生成、会话隔离、Word 上传、'
                   '模型断点续传、备份导出/导入、报修记录、窗口记忆、后端日志、更新检查、'
                   '前端单元测试与分包、联网搜索、Windows/macOS/Linux 构建配置、PWA。',
        'tree': tree['sha'],
        'parents': [parent],
    })
    call('PATCH', f'{repo_path}/git/refs/heads/{branch}', token, {'sha': commit['sha'], 'force': False})
    print('pushed commit:', commit['sha'])
    print('repository:', f'https://github.com/{args.owner}/{args.repo}')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print('publish failed:', error, file=sys.stderr)
        sys.exit(1)
