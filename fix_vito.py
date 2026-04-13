with open('/home/ubuntu/.openclaw/workspace/workers/uncle_vito/vito_report.py', 'r') as f:
    content = f.read()

# Find the specific pattern - the end of the confidence parlay if block
# It's the conf_parlay_html = f'''... block that ends with </div>'''
old_ending = """            </div>'''
        
        html = html.replace("__DATE_STR__", date_str)
        html = html.replace("__CONFIDENCE_PARLAY__", conf_parlay_html)"""

new_ending = """            </div>'''
        else:
            # Always show the section even when empty
            conf_parlay_html = \'\'\'''<div class="confidence-parlay">
                <div class="confidence-parlay-header">
                    <span class="confidence-parlay-icon">🌐</span>
                    <span class="confidence-parlay-title">CONFIDENCE PARLAY</span>
                    <span class="confidence-parlay-meta">all leagues</span>
                </div>
                <div class="confidence-parlay-picks">
                    <div class="confidence-pick-item">
                        <span class="confidence-pick-text" style="color: var(--text-dim);">Loading picks...</span>
                    </div>
                </div>
                <div class="confidence-parlay-footer">
                    <span class="confidence-parlay-odds">—</span>
                    <span class="confidence-parlay-avg">🎯 —% avg confidence</span>
                </div>
            </div>\'\'\'
        
        html = html.replace("__DATE_STR__", date_str)
        html = html.replace("__CONFIDENCE_PARLAY__", conf_parlay_html)"""

if old_ending in content:
    content = content.replace(old_ending, new_ending)
    print('Found and replaced')
else:
    print('Pattern not found')
    # Try to find what's actually there
    idx = content.find("html = html.replace(\"__DATE_STR__\"")
    if idx > 0:
        print('Found replacement at:', idx)
        print('Context:', repr(content[idx-200:idx+100]))

with open('/home/ubuntu/.openclaw/workspace/workers/uncle_vito/vito_report.py', 'w') as f:
    f.write(content)
print('Done')
