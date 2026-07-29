import importlib.util

# Load v5.4 (new)
spec_new = importlib.util.spec_from_file_location('v5_4_new', r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\v5.4_FSRS_full.py')
m_new = importlib.util.module_from_spec(spec_new)
spec_new.loader.exec_module(m_new)

# Load v5.2 (old - 3 grade)
spec_old = importlib.util.spec_from_file_location('v5_2', r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\v5.2_FSRSv6.py')
m_old = importlib.util.module_from_spec(spec_old)
spec_old.loader.exec_module(m_old)

print("=== Comparison: v5.2 (3-grade) vs v5.4 (4-grade with persona) ===\n")

for plan in ["free", "silver", "gold"]:
    for persona_key in ["eager", "average", "lazy"]:
        for days in [30, 90, 180, 360]:
            cfg_old = m_old.SimConfig(plan=plan, persona=persona_key, proficiency="intermediate", 
                                       days=days, seed=42, mastery_model="dsr", enable_rejection=False)
            _, s_old = m_old.simulate(cfg_old)
            
            cfg_new = m_new.SimConfig(plan=plan, persona=persona_key, days=days, seed=42, enable_rejection=False)
            _, s_new = m_new.simulate(cfg_new)
            
            learned_old = s_old["learned_words"]
            learned_new = s_new["learned_words"]
            ratio = learned_new / learned_old if learned_old > 0 else 0
            
            print(f"  {plan}/{persona_key}/{days}d: v5.2={learned_old} v5.4={learned_new} ratio={ratio:.2f}")

print("\n=== 720-day stress test ===")
for plan in ["gold"]:
    for persona_key in ["eager", "average", "lazy"]:
        cfg_old = m_old.SimConfig(plan=plan, persona=persona_key, proficiency="intermediate", 
                                   days=720, seed=42, mastery_model="dsr", enable_rejection=False)
        _, s_old = m_old.simulate(cfg_old)
        
        cfg_new = m_new.SimConfig(plan=plan, persona=persona_key, days=720, seed=42, enable_rejection=False)
        _, s_new = m_new.simulate(cfg_new)
        
        print(f"  {plan}/{persona_key}: v5.2 learned={s_old['learned_words']}, v5.4 learned={s_new['learned_words']}, ratio={s_new['learned_words']/s_old['learned_words']:.2f}")
        print(f"    v5.2: avg_late={s_old['avg_lateness_days']:.1f}, max_late={s_old['max_lateness_days']}")
        print(f"    v5.4: avg_late={s_new['avg_lateness_days']:.1f}, max_late={s_new['max_lateness_days']}")