"""Smoke test bằng HTTP: hai agent phải đang chạy trước; dùng ID task mới mỗi lần."""
import json
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
ROOT = Path(__file__).resolve().parent.parent

def get_key(role):
    path = ROOT / 'agents' / role / '.env'
    if not path.is_file():
        raise RuntimeError(f"Chưa có {path}, chạy python scripts/setup_dev_scrum.py")
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('AGENT_API_KEY='):
            key=line.partition('=')[2].strip()
            if key: return key
    raise RuntimeError(f"Không có token trong {path}")

def get(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=6) as response:
        return json.loads(response.read())

def post(url, obj, key):
    req = Request(url, data=json.dumps(obj, ensure_ascii=False).encode('utf-8'), method='POST',
                  headers={'Authorization':f'Bearer {key}', 'Content-Type':'application/json'})
    with urlopen(req, timeout=700) as r:
        return json.loads(r.read())

for role, port, sample in [('dev',8006,'implement.json'),('scrum_master',8009,'track.json')]:
    host=f'http://127.0.0.1:{port}'
    try:
        health=get(host+'/health')
        assert health['status']=='healthy'
        key=get_key(role)
        who=get(host+'/agent',{'Authorization':f'Bearer {key}'})
        task=json.loads((ROOT/'agents'/role/'examples'/sample).read_text(encoding='utf-8'))
        task['task_id'] += '-' + uuid.uuid4().hex[:7]
        outcome=post(host+'/tasks',task,key)
        print(f"[{role}] /health: {health['role']}; agent={who['agent_id']}; task={outcome['status']}")
        print('  summary:',outcome['summary'])
        print('  artifact:',[(a['name'],a['type']) for a in outcome.get('artifacts',[])])
    except (HTTPError,URLError,RuntimeError,AssertionError) as e:
        print(f"[ERROR] {role}: {e}")
        raise
