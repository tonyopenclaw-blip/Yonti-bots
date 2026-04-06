#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/workers/uncle_vito')

from vito_report import UncleVitoReport
import config

report = UncleVitoReport()
report.fetch_todays_games()
output = report.format_report()
print(output[:4000])
