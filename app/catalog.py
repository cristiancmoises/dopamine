"""Real, unique inventory; historical fictional purchases are kept separately."""
import json
import unicodedata
from pathlib import Path
from .config import ROOT

SEEDS=json.loads((ROOT/'data/catalog.json').read_text())
_live=ROOT/'data/catalog-live.json'
DATA=json.loads(_live.read_text()) if _live.is_file() else SEEDS
PHOTOS={}
_resolved=ROOT/'data/photos-resolved.json'
if _live.is_file() and _resolved.is_file():PHOTOS=json.loads(_resolved.read_text())
PRODUCTS={p['id']:p for p in DATA['products']}
CATEGORIES={c['id']:c for c in DATA['categories']}
LEGACY={p['id']:p for p in json.loads((ROOT/'data/legacy-catalog-110.json').read_text())['products']}

def folded(value):return ''.join(c for c in unicodedata.normalize('NFKD',value).casefold() if not unicodedata.combining(c))

def localize(p,lang):
    q=dict(p);q['type']=p['type'][lang];q['category_label']=CATEGORIES[p['category']]['label'][lang]
    q['image']='/static/photos/'+p['photo']+'.webp';q['photo_credit']=PHOTOS.get(p['photo'],{})
    return q

def historical(pid,lang):
    if pid in PRODUCTS:return localize(PRODUCTS[pid],lang)
    p=LEGACY.get(pid,{})
    # Never relabel an old purchase as a real branded product or show a wrong photo.
    return {'id':pid,'name':p.get('name',pid),'image':'','photo':'','type':p.get('type',{}).get(lang,''),'legacy':True}

def select(lang,category='',query='',sort='curated',favorite_ids=None):
    results=[localize(p,lang) for p in PRODUCTS.values() if not category or p['category']==category]
    if query:
        needle=folded(query);results=[p for p in results if needle in folded(p['name']+' '+p['type']+' '+p['category_label'])]
    if favorite_ids is not None:results=[p for p in results if p['id'] in favorite_ids]
    keys={'curated':lambda p:p['rank'],'low':lambda p:p['credits'],'high':lambda p:-p['credits'],'name':lambda p:p['name']}
    return sorted(results,key=keys.get(sort,keys['curated']))

def validate():
    assert len(PRODUCTS)==len(DATA['products']), 'Duplicate product ID'
    assert len({folded(p['name']) for p in PRODUCTS.values()})==len(PRODUCTS),'Duplicate model name'
    assert len({p['photo'] for p in PRODUCTS.values()})==len(PRODUCTS),'Repeated photo slot'
    for p in PRODUCTS.values():
        assert p['category'] in CATEGORIES
        assert isinstance(p['credits'],int) and 0<p['credits']<10**12
        assert set(p['type'])=={'pt-br','en','zh','ja'}
    return len(PRODUCTS)
