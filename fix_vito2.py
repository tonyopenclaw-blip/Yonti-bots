with open('/home/ubuntu/.openclaw/workspace/workers/uncle_vito/vito_report.py', 'r') as f:
    content = f.read()

# Fix the broken else block - replace the mangled version with correct version
old = """            </div>'''
        else:
            # Always show the section even when empty
            conf_parlay_html = '<div class="confidence-parlay">
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
            </div>'
        
        html = html.replace("__DATE_STR__", date_str)"""

new = """            </div>'''
        else:
            # Always show the section even when empty
            conf_parlay_html = \'\'\'<div class="confidence-parlay">
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
        
        html = html.replace("__DATE_STR__", date_str)"""

if old in content:
    content = content.replace(old, new)
    print('Fixed!')
else:
    print('Pattern not found')

with open('/home/ubuntu/.openclaw/workspace/workers/uncle_vito/vito_report.py', 'w') as f:
    f.write(content)
