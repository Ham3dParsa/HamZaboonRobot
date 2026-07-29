import importlib.util
spec = importlib.util.spec_from_file_location('v5_4', r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\v5.4_FSRS_full.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Test grade distributions for each persona
import random
rng = random.Random(42)

for persona_key in ["eager", "average", "lazy", "fluctuating"]:
    persona = m.PERSONAS[persona_key]
    # Simulate 10000 first exposures
    grades = []
    for _ in range(10000):
        grade = m._sample_grade(persona["persona_key"], 1.0, rng)
        grades.append(grade)
    
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for g in grades:
        counts[g] += 1
    
    total = len(grades)
    print(f"{persona_key}: Again={counts[1]/total*100:.1f}%, Hard={counts[2]/total*100:.1f}%, Good={counts[3]/total*100:.1f}%, Easy={counts[4]/total*100:.1f}%")

# Test retrievability modulation
print("\n--- Retrievability modulation test ---")
rng = random.Random(123)
for r in [1.0, 0.9, 0.7, 0.5, 0.3, 0.1]:
    grades = []
    for _ in range(5000):
        grade = m._sample_grade("average", r, rng)
        grades.append(grade)
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for g in grades:
        counts[g] += 1
    total = len(grades)
    print(f"R={r}: Again={counts[1]/total*100:.1f}%, Hard={counts[2]/total*100:.1f}%, Good={counts[3]/total*100:.1f}%, Easy={counts[4]/total*100:.1f}%")

# Full simulation test
print("\n--- Full simulation test (360 days) ---")
for persona_key in ["eager", "average", "lazy"]:
    cfg = m.SimConfig(plan='gold', persona=persona_key, days=360, seed=42, enable_rejection=False)
    _, s = m.simulate(cfg)
    print(f"  {persona_key}: learned={s['learned_words']}, avg_late={s['avg_lateness_days']:.1f}, max_late={s['max_lateness_days']}")