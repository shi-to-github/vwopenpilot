"""Read saved logs for actual EPS refusals; does not connect or send CAN."""
from bisect import bisect_left, bisect_right
from collections import Counter
import json
from pathlib import Path
from review_v3_road_logs import when, runs

ROOT=Path(__file__).resolve().parents[1]


def audit():
  paths={}
  for p in (ROOT/'device-backups').rglob('*.jsonl'):
    if (p.name.startswith('v3-20') or p.name.startswith('probe-20')):
      if p.name not in paths or p.stat().st_size>paths[p.name].stat().st_size:
        paths[p.name]=p
  reports=[]
  for p in sorted(paths.values()):
    eps,states,controls,sent=[],[],[],[]
    count=Counter(); bad=0; first=last=None
    for line in p.open(encoding='utf-8'):
      try:r=json.loads(line)
      except ValueError:bad+=1;continue
      kind=r['type'];count[kind]+=1
      if 't_mono_ns' in r:
        t=when(r);first=t if first is None else min(first,t);last=t if last is None else max(last,t)
      if kind=='can' and r.get('address')==978 and r.get('src')==0:eps.append(r)
      elif kind=='pq46_status':states.append(r)
      elif kind=='controlsState':controls.append(r)
      elif kind=='sendcan' and r.get('address')==210:sent.append(r)
    for rows in (eps,states,controls,sent):rows.sort(key=when)
    et=[when(r) for r in eps];st=[when(r) for r in states];ct=[when(r) for r in controls]
    refusals=[]
    for group in runs(eps,lambda r:r.get('eps_hca_status') in (2,4),maximum_gap=.15):
      t=when(group[0]);si=bisect_right(st,t)-1;ci=bisect_right(ct,t)-1
      refusals.append({'t_s':t,'status':group[0]['eps_hca_status'],
                        'duration_s':when(group[-1])-t,
                        'hca_before':states[si]['hca'] if si>=0 and t-st[si]<.3 else None,
                        'controls_before':controls[ci] if ci>=0 and t-ct[ci]<.3 else None})
    deadlines=[];prior=False
    for r in states:
      h=r['hca'];flag=h.get('takeover_required',False);t=when(r)
      if flag and not prior:
        near=eps[bisect_left(et,t-2):bisect_right(et,t)]
        alerts=controls[bisect_left(ct,t):bisect_right(ct,t+3.5)]
        deadlines.append({'t_s':t,'timer_age_s':h['elapsed_s'],
                          'eps_before':dict(Counter(n['eps_hca_status'] for n in near)),
                          'alerts_after':dict(Counter(n.get('alertType','not_recorded') for n in alerts))})
      prior=flag
    continuous=runs(eps,lambda r:r.get('eps_hca_status')==5,maximum_gap=.15)
    longest=max(continuous,key=lambda g:when(g[-1])-when(g[0]),default=[])
    reports.append({'file':str(p.relative_to(ROOT)),'minutes':(last-first)/60 if first is not None else 0,
                    'invalid_lines':bad,'counts':dict(count),'has_eps_feedback':bool(eps),
                    'versions':dict(Counter(r['hca'].get('version','unlabelled') for r in states)),
                    'eps_counts':dict(Counter(r['eps_hca_status'] for r in eps)),
                    'actual_refusals':refusals,'software_deadlines':deadlines,
                    'max_software_age_s':max((r['hca']['elapsed_s'] for r in states),default=None),
                    'longest_observed_eps_active_run_s':when(longest[-1])-when(longest[0]) if longest else None,
                    'note':'EPS active-run duration is observed acceptance, not its internal timer. Gaps and standby break the run; sessions may begin mid-run.'})
  result={'files':reports,'eps_frames':sum(sum(r['eps_counts'].values()) for r in reports),
          'actual_refusal_runs':sum(len(r['actual_refusals']) for r in reports),
          'software_deadlines':sum(len(r['software_deadlines']) for r in reports),
          'longest_observed_eps_active_run_s':max((r['longest_observed_eps_active_run_s'] or 0 for r in reports),default=0),
          'conclusion':'No hardware timeout can be inferred from software takeover ages; probe logs without EPS frames cannot establish a hardware refusal.'}
  out=ROOT/'device-backups/eps-timeout-audit-latest.json'
  out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({k:v for k,v in result.items() if k!='files'}))
  for r in reports:
    print(json.dumps({k:v for k,v in r.items() if k not in ('counts','software_deadlines','note')},ensure_ascii=True))
  return result


if __name__=='__main__':audit()
