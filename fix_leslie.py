# Simple script to fix Leslie's login error line
with open('leslies-log-and-plot.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix: lines 304-305 now need to have the skip logic
# Keep the skip, add a print, and properly indent the subsequent lines

# Insert the print statement after the comment
lines.insert(305, '        print("Leslie login failed. Skipping.")\n')
lines.insert(306, '        return\n\n')

# Now line 306 is the fetch data - it shouldn't run if login failed
# Actually we need to check if there's code after that needs to be skipped
# Looking at the original, there was a raise RuntimeError here
# But now the skip logic means we return before fetch_data() runs

with open('leslies-log-and-plot.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
    
print('File updated - login skip logic added')
