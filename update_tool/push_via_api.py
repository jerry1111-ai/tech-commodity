# -*- coding: utf-8 -*-
"""通过 GitHub REST API 推送（绕过对 github.com:443 的代理限制）。

增量推送：只上传内容有变化的文件（对比远程 tree 的 blob sha），
大幅减少传输量。Token 从环境变量 GIT_TOKEN 或本地 .token 读取，可进定时任务。
"""
import os
import sys
import base64
import hashlib
import subprocess

import requests

OWNER = "jerry1111-ai"
REPO = "tech-commodity"
BRANCH = "main"
API = "https://api.github.com"


def get_token():
    t = os.environ.get("GIT_TOKEN", "").strip()
    if t:
        return t
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def main():
    token = get_token()
    if not token:
        print("缺少 GIT_TOKEN 环境变量或 .token 文件")
        sys.exit(1)

    s = requests.Session()
    s.trust_env = False
    s.proxies = {}
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}

    # 1. 远程当前 commit + tree
    r = s.get(f"{API}/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}", headers=h, timeout=30)
    if r.status_code != 200:
        print("获取 ref 失败:", r.status_code, r.text[:200]); sys.exit(1)
    parent_sha = r.json()["object"]["sha"]

    r = s.get(f"{API}/repos/{OWNER}/{REPO}/git/commits/{parent_sha}", headers=h, timeout=30)
    base_tree = r.json()["tree"]["sha"]

    # 2. 远程已有文件的 sha 映射（递归取全部）
    remote = {}
    rt = s.get(f"{API}/repos/{OWNER}/{REPO}/git/trees/{base_tree}?recursive=1", headers=h, timeout=60)
    if rt.status_code == 200:
        for it in rt.json().get("tree", []):
            if it.get("type") == "blob":
                remote[it["path"]] = it["sha"]

    # 3. 本地文件清单（先 add -A 纳入新建文件，git ls-files 遵守 .gitignore）
    subprocess.run(["git", "add", "-A"], capture_output=True)
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8")
    files = [f for f in out.stdout.splitlines() if f.strip()]

    changed = []
    for f in files:
        if not os.path.exists(f):
            continue
        with open(f, "rb") as fp:
            data = fp.read()
        if remote.get(f.replace("\\", "/")) == blob_sha(data):
            continue  # 内容未变，跳过
        changed.append((f, data))

    if not changed:
        print("无变化，跳过推送")
        return

    print(f"远程 HEAD {parent_sha[:8]}；本地 {len(files)} 文件，需上传 {len(changed)} 个")

    # 4. 上传变化的 blob（相同内容只传一次，如 index.html 与主 HTML 内容一致）
    tree_items = []
    total = 0
    sha_cache = {}
    for i, (f, data) in enumerate(changed, 1):
        total += len(data)
        sha = blob_sha(data)
        if sha in sha_cache:
            tree_items.append({"path": f.replace("\\", "/"), "mode": "100644",
                               "type": "blob", "sha": sha_cache[sha]})
            continue
        b = s.post(f"{API}/repos/{OWNER}/{REPO}/git/blobs", headers=h,
                   json={"content": base64.b64encode(data).decode(), "encoding": "base64"},
                   timeout=120)
        if b.status_code not in (200, 201):
            print(f"  blob 失败 {f}: {b.status_code}"); continue
        sha_cache[sha] = b.json()["sha"]
        tree_items.append({"path": f.replace("\\", "/"), "mode": "100644",
                           "type": "blob", "sha": b.json()["sha"]})
        if i % 20 == 0:
            print(f"  已上传 {i}/{len(changed)} ({total/1024/1024:.1f}MB)")

    if not tree_items:
        print("无成功上传")
        sys.exit(1)

    # 5. tree / commit / ref
    t = s.post(f"{API}/repos/{OWNER}/{REPO}/git/trees", headers=h,
               json={"base_tree": base_tree, "tree": tree_items}, timeout=120)
    if t.status_code not in (200, 201):
        print("创建 tree 失败:", t.status_code, t.text[:300]); sys.exit(1)

    c = s.post(f"{API}/repos/{OWNER}/{REPO}/git/commits", headers=h,
               json={"message": "自动更新: 行情/评分/K线/宏观/选股/外盘",
                     "tree": t.json()["sha"], "parents": [parent_sha]}, timeout=60)
    if c.status_code not in (200, 201):
        print("创建 commit 失败:", c.status_code, c.text[:300]); sys.exit(1)
    new_commit = c.json()["sha"]

    p = s.patch(f"{API}/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", headers=h,
                json={"sha": new_commit, "force": False}, timeout=60)
    if p.status_code not in (200, 201):
        print("更新 ref 失败:", p.status_code, p.text[:300]); sys.exit(1)

    print(f"推送成功 {new_commit[:8]}：上传 {len(tree_items)} 文件 {total/1024/1024:.2f}MB")


if __name__ == "__main__":
    main()
