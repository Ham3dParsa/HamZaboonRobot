with open(r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\report_v52_v54.html', 'r', encoding='utf-8') as f:
    content = f.read()

sections = ['s1', 's2', 's3', 's4', 's5', 's6', 's7']
for s in sections:
    if 'id="' + s + '"' in content:
        print('Section ' + s + ': FOUND')
    else:
        print('Section ' + s + ': MISSING')

for cls in ['row-best', 'row-worst', 'p50', 'p90', 'p95', 'p99']:
    count = content.count('class="' + cls + '"') + content.count('class="' + cls + ' ')
    print('Class ' + cls + ': ' + str(count) + ' occurrences')

table_count = content.count('<table>')
print('Tables: ' + str(table_count))

import os
print('File size: ' + str(os.path.getsize(r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\report_v52_v54.html')) + ' bytes')