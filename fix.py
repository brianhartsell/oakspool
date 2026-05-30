# Copy the file and strip problematic chars
import re
with open('leslies-log-and-plot.py', 'rb') as f:
    raw = f.read()
content = raw.decode('utf-8', errors='replace')
# Fix line 304-305
lines = content.split('\n')
lines[304] = '    if not api.authenticate():'  # Line 305 was 0-indexed 304
lines[305] = '        # Leslie login failed - skip this run'
lines.insert(306, '        print("Leslie login failed. Skipping.")')
lines.insert(307, '        return')
with open('leslies-log-and-plot.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Done')
