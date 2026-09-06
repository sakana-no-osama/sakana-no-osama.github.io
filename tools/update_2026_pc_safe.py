"""Read-only safety check for the 2026 ranking workflow."""
import os, subprocess, sys
from pathlib import Path

if hasattr(sys.stdout,'reconfigure'):
 sys.stdout.reconfigure(encoding='utf-8',errors='replace')
if hasattr(sys.stderr,'reconfigure'):
 sys.stderr.reconfigure(encoding='utf-8',errors='replace')

ROOT=Path(__file__).resolve().parents[1]
VERIFIERS=[
 ('rankings',ROOT/'tests'/'verify_2026_rankings.py'),
 ('standings/fixtures',ROOT/'tests'/'verify_2026_standings_fixtures.py'),
 ('match scorers',ROOT/'tests'/'verify_2026_match_scorers.py'),
]
REQUIRED=[ROOT/x for x in ('scripts','data','tests','docs','index.html')]
def run(a):
 env=os.environ.copy(); env['PYTHONIOENCODING']='utf-8'
 return subprocess.run(a,cwd=ROOT,text=True,encoding='utf-8',errors='replace',capture_output=True,check=False,env=env)
def main():
 h=[]; f=[]
 b=run(['git','branch','--show-current']); branch=b.stdout.strip(); print('branch:',branch or '(unknown)')
 if b.returncode or not branch: f.append('cannot determine branch')
 elif branch=='main': h.append('create a work branch before updating')
 s=run(['git','status','--short','--branch']); print('git status:\n'+s.stdout.rstrip())
 if s.returncode: f.append('git status failed')
 elif any(not x.startswith('##') for x in s.stdout.splitlines()): h.append('worktree has changes or untracked files')
 for p in REQUIRED:
  ok=p.exists(); print(('PASS' if ok else 'FAIL')+': '+str(p.relative_to(ROOT)))
  if not ok: f.append('missing: '+str(p.relative_to(ROOT)))
 for label,verify in VERIFIERS:
  print('verify:',label)
  if verify.exists():
   v=run([sys.executable,str(verify)]); print(v.stdout.rstrip())
   if v.stderr: print(v.stderr.rstrip(),file=sys.stderr)
   if v.returncode: f.append(label+' verify exit code: '+str(v.returncode))
   if 'VERDICT=PASS' not in v.stdout: f.append(label+' verification did not PASS')
  else: f.append('missing verification script: '+str(verify.relative_to(ROOT)))
 verdict='FAIL' if f else ('HOLD' if h else 'PASS'); print('VERDICT='+verdict)
 for r in f+h: print(verdict+'_REASON='+r)
 return 1 if f else (2 if h else 0)
if __name__=='__main__': raise SystemExit(main())
