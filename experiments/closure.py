import json,sys

# Unlock-closure check. Usage: python experiments/closure.py [level.json]
# Answers: how many species can Level N ever reach? Optimistic upper bound.
LEVEL=sys.argv[1] if len(sys.argv)>1 else 'resources-docs/1(1).json'
plants=json.load(open('resources-docs/plant_dataset.json'))
unlocks=json.load(open('resources-docs/plant_unlock_conditions.json'))
animals=json.load(open('resources-docs/animals.json'))
world=json.load(open(LEVEL))

animal_ids=set()
for a in animals if isinstance(animals,list) else animals.get('animals',[]):
    animal_ids.add(a.get('id')); animal_ids.add(a.get('name'))
animal_ids.discard(None)
print("ANIMAL SPECIES:", sorted(animal_ids))
print("animals_enabled:", world['animals_enabled'])
print("commands:", json.dumps(world['commands']))
plant_names={p['plant'] for p in plants}
STARTERS={"Grass","Rose Bush","Lavender","Dwarf Sunflower","Oak Tree"}

# OPTIMISTIC evaluation: assume ANY unlocked plant can reach ANY coverage/count.
# animals never present (animals_enabled false). No events scheduled.
EVENTS={c.get('event') for c in world['commands'] if c.get('type')=='event'}
EVENTS.discard(None)

def ev(node, avail):
    if 'op' in node:
        op=node['op']
        if op=='AND': return all(ev(c,avail) for c in node['children'])
        if op=='OR':  return any(ev(c,avail) for c in node['children'])
        if op=='NOT': return not ev(node['child'],avail)
        raise ValueError(op)
    t=node['type']
    if t=='species_present':
        s=node['species']
        if s in animal_ids: return False        # animals disabled
        return s in avail                        # a plant species
    if t=='species_absent':
        s=node['species']
        if s in animal_ids: return True          # animals can never be present
        return s not in avail                    # optimistic: we can choose not to plant it
    if t in ('coverage','count'):
        return node['plant'] in avail            # optimistic: assume threshold reachable
    if t=='event':
        return node['event'] in EVENTS
    if t=='feature_count':
        f=node['feature']
        if f=='dead_matter': return True         # reachable: plants die -> dead matter
        if f=='burnt_soil': return 'Emberroot Tree' in avail
        return False
    raise ValueError(t)

avail=set(STARTERS)
changed=True
order=[]
while changed:
    changed=False
    for u in unlocks:
        p=u['plant']
        if p in avail: continue
        if ev(u['unlock'], avail):
            avail.add(p); order.append(p); changed=True

print("\n=== OPTIMISTIC CLOSURE (level 1: no animals, no events) ===")
print("reachable count:", len(avail))
print("unlocked beyond starters:", order)
blocked=sorted(plant_names-avail)
print("\nBLOCKED (%d):"%len(blocked))
for b in blocked:
    node=next((u['unlock'] for u in unlocks if u['plant']==b), None)
    print("  ", b)
