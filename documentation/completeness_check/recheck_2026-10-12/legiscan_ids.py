import json,glob,csv,re,collections,sys
S=sys.argv[1]
L=json.load(open('legislators-current.json'))+json.load(open('legislators-historical.json'))
uni={u['bioguide']:u for u in csv.DictReader(open(S+"/universe.csv"))}
vs={};os_={}
for p in L:
    b=p['id']['bioguide']
    if b not in uni: continue
    if p['id'].get('votesmart'): vs[str(p['id']['votesmart'])]=b
    if p['id'].get('opensecrets'): os_[p['id']['opensecrets']]=b
hits=collections.defaultdict(set); sessions={}; bad=0
def load(fn):
    try: d=json.load(open(fn))
    except Exception: return {}
    return d if isinstance(d,dict) else {}
for fn in glob.glob('legiscan_session_cache/sessionlist_*.json'):
    ss=load(fn).get('sessions',[])
    for s in ss if isinstance(ss,list) else []: sessions[s['session_id']]=s['session_name']
for fn in glob.glob('legiscan_session_cache/sessionpeople_*.json'):
    sid=int(re.search(r'_(\d+)\.json',fn).group(1)); sp=load(fn).get('sessionpeople')
    if not isinstance(sp,dict) or 'people' not in sp: bad+=1; continue
    for pe in (sp['people'] if isinstance(sp['people'],list) else []):
        if not isinstance(pe,dict): continue
        for key,m in (('bioguide_id',{b:b for b in uni}),('votesmart_id',vs),('opensecrets_id',os_)):
            v=str(pe.get(key) or '')
            if v and v!='0' and v in m:
                hits[m[v]].add((pe['name'],pe['role'],pe['district'],sessions.get(sid,'?'),key))
print('unreadable session files',bad,'sessions named',len(sessions))
print(len(hits),'universe members in LegiScan state sessions by ID;', sum(uni[b]['in_pop']=='True' for b in hits),'in pop')
w=csv.writer(open(S+'/legiscan_hits.csv','w')); w.writerow(['bioguide','in_pop','n','example'])
for b,h in sorted(hits.items()):
    w.writerow([b,uni[b]['in_pop'],len(h),sorted(h)[0]])
    if uni[b]['in_pop']=='False':
        print(b,uni[b]['name'],uni[b]['state'],len(h),sorted(h)[:2])
