"""Server-authoritative practice tables. No purchases, balances, cash-out or autoplay.

A table can lose. A separate demo grant refunds the simulated stake and adds 100
units; neither the grant nor the infinite wallet changes the table's outcome.
Rules are deliberately explicit variants, not claims of casino certification.
"""
from copy import deepcopy
import secrets

TABLES = ('roulette','blackjack','baccarat','slots','dice','keno','plinko')
STAKES = (100,500,1000)
WHEEL = (0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26)
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
SYMBOLS = ('7','◆','★','♠','♥','●')
SLOT_MULTIPLIERS = (50,25,15,10,8,7)  # total return; any exact pair returns 1x
KENO_MULTIPLIERS = (0,0,1,3,10,50)  # five picks, draw ten from forty
PLINKO_MULTIPLIERS = (8,3,1,0.5,0,0.5,1,3,8)
RNG = secrets.SystemRandom()

class InvalidMove(ValueError): pass

def deck(rng=RNG, copies=1):
    cards=[{'rank':rank,'suit':suit} for _ in range(copies) for suit in ('♠','♥','♦','♣') for rank in ('A','2','3','4','5','6','7','8','9','10','J','Q','K')]
    rng.shuffle(cards)
    return cards

def hand_value(cards):
    total=sum(11 if c['rank']=='A' else 10 if c['rank'] in ('J','Q','K') else int(c['rank']) for c in cards)
    aces=sum(c['rank']=='A' for c in cards)
    while total>21 and aces:total-=10;aces-=1
    return total, bool(aces)

def baccarat_value(cards):
    return sum(1 if c['rank']=='A' else 0 if c['rank'] in ('10','J','Q','K') else int(c['rank']) for c in cards)%10

def settled(s, returned):
    s.update(completed=True,table_return=int(returned),table_net=int(returned)-s['stake'],demo_refund=s['stake'],demo_bonus=100)
    s['outcome']='win' if returned>s['stake'] else 'push' if returned==s['stake'] else 'loss'
    return s

def base(game,stake):
    if game not in TABLES or type(stake) is not int or stake not in STAKES:raise InvalidMove('Invalid table or stake')
    return {'game':game,'stake':stake,'completed':False,'table_return':0,'table_net':0,'demo_refund':0,'demo_bonus':0,'outcome':'playing'}

def start(game, stake, form, rng=RNG):
    s=base(game,stake)
    choice=str(form.get('choice',''))
    if game=='roulette':
        if choice not in ('red','black','odd','even','low','high','number'):raise InvalidMove('Choose a bet')
        raw=str(form.get('number','0'))
        if not raw.isdigit() or not 0<=int(raw)<=36:raise InvalidMove('Choose one number from 0 to 36')
        n=rng.randrange(37);number=int(raw)
        wins={'red':n in RED,'black':n!=0 and n not in RED,'odd':n!=0 and n%2==1,'even':n!=0 and n%2==0,'low':1<=n<=18,'high':19<=n<=36,'number':n==number}
        s.update(choice=choice,number=number,pocket=n,wheel_index=WHEEL.index(n),pocket_color='green' if n==0 else 'red' if n in RED else 'black')
        return settled(s,stake*(36 if choice=='number' else 2) if wins[choice] else 0)
    if game=='blackjack':
        d=deck(rng);p=[d.pop()];dealer=[d.pop()];p.append(d.pop());dealer.append(d.pop())
        s.update(deck=d,player=p,dealer=dealer,can_double=True)
        pn=hand_value(p)[0]==21;dn=hand_value(dealer)[0]==21
        if pn or dn:
            s['can_double']=False
            return settled(s,stake if pn and dn else stake*5//2 if pn else 0)
        return s
    if game=='baccarat':
        if choice not in ('player','banker','tie'):raise InvalidMove('Choose a side')
        d=deck(rng,8);p=[d.pop()];b=[d.pop()];p.append(d.pop());b.append(d.pop())
        pv,bv=baccarat_value(p),baccarat_value(b)
        if pv<8 and bv<8:
            if pv<=5:
                p.append(d.pop());third=baccarat_value(p[-1:])
                draw=(bv<=2 or bv==3 and third!=8 or bv==4 and 2<=third<=7 or bv==5 and 4<=third<=7 or bv==6 and third in (6,7))
            else:draw=bv<=5
            if draw:b.append(d.pop())
        pv,bv=baccarat_value(p),baccarat_value(b)
        winner='player' if pv>bv else 'banker' if bv>pv else 'tie'
        returned=stake if winner=='tie' and choice!='tie' else stake*9 if choice==winner=='tie' else stake*195//100 if choice==winner=='banker' else stake*2 if choice==winner=='player' else 0
        s.update(choice=choice,player=p,banker=b,player_total=pv,banker_total=bv,winner=winner)
        return settled(s,returned)
    if game=='slots':
        reels=[rng.randrange(6) for _ in range(3)]
        s.update(reels=[SYMBOLS[x] for x in reels])
        mult=SLOT_MULTIPLIERS[reels[0]] if len(set(reels))==1 else 1 if len(set(reels))==2 else 0
        return settled(s,stake*mult)
    if game=='dice':
        if choice not in ('under','seven','over'):raise InvalidMove('Choose a total')
        dice=[rng.randint(1,6),rng.randint(1,6)];total=sum(dice)
        won=total<7 if choice=='under' else total>7 if choice=='over' else total==7
        s.update(choice=choice,dice=dice,total=total)
        return settled(s,stake*(5 if choice=='seven' else 2) if won else 0)
    if game=='keno':
        try:picks=[int(str(form.get('pick'+str(i),''))) for i in range(1,6)]
        except (ValueError,TypeError):raise InvalidMove('Choose five different numbers')
        if len(set(picks))!=5 or any(x<1 or x>40 for x in picks):raise InvalidMove('Choose five different numbers from 1 to 40')
        drawn=rng.sample(range(1,41),10);hits=sorted(set(picks)&set(drawn))
        s.update(picks=sorted(picks),drawn=drawn,hits=hits)
        return settled(s,stake*KENO_MULTIPLIERS[len(hits)])
    if game=='plinko':
        bits=[rng.randrange(2) for _ in range(8)];slot=sum(bits)
        s.update(steps=bits,slot=slot,multiplier=PLINKO_MULTIPLIERS[slot])
        return settled(s,int(stake*PLINKO_MULTIPLIERS[slot]))
    raise InvalidMove('Unknown table')

def move(state,action):
    s=deepcopy(state)
    if s['completed'] or s['game']!='blackjack' or action not in ('hit','stand','double'):raise InvalidMove('This action is unavailable')
    if action=='double':
        if not s['can_double'] or len(s['player'])!=2:raise InvalidMove('Double is available only on the first decision')
        s['stake']*=2
    s['can_double']=False
    if action in ('hit','double'):
        s['player'].append(s['deck'].pop())
        p=hand_value(s['player'])[0]
        if p>21:return settled(s,0)
        if action=='hit' and p<21:return s
    while hand_value(s['dealer'])[0]<17:s['dealer'].append(s['deck'].pop())
    p=hand_value(s['player'])[0];d=hand_value(s['dealer'])[0]
    return settled(s,s['stake']*2 if d>21 or p>d else s['stake'] if p==d else 0)

def public(state):
    s={k:deepcopy(v) for k,v in state.items() if k!='deck'}
    if s['game']=='blackjack':
        if not s['completed']:s['dealer']=[s['dealer'][0],{'rank':'?','suit':''}]
        s['player_total']=hand_value(s['player'])[0]
        s['dealer_total']=hand_value(s['dealer'])[0] if s['completed'] else '?'
    return s
