import importlib.util
spec = importlib.util.spec_from_file_location('v5_4', r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\v5.4_FSRS_full.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
cfg = m.SimConfig(plan='silver', persona='eager', days=30, seed=42, enable_rejection=False)
_, s = m.simulate(cfg)
print('v5.4 simulation works!')
print('  learned:', s['learned_words'], 'avg_late:', s['avg_lateness_days'], 'max_late:', s['max_lateness_days'])
print('  tier_counts:', s['tier_counts'])