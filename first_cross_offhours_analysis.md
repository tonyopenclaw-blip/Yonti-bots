
================================================================================
FIRST_CROSS OFF-HOURS ANALYSIS (00:00-14:00 UTC)
Session: 2026-04-07 00:00-00:46 UTC
================================================================================

📊 SUMMARY
--------------------------------------------------------------------------------
Total FIRST_CROSS trades in session:      8
Off-hours FIRST_CROSS trades (00-14 UTC):  5
  - Reached expiry:                       2
  - Closed by trailing stop:              3

📈 EXPIRY RESULTS (Direction Match Analysis)
--------------------------------------------------------------------------------
Only 2 off-hours FIRST_CROSS trades reached expiry:

Trade 1: KXETH15M-26APR062015-15
  Entry Time:   2026-04-07 00:02:10 UTC
  Entry Side:   YES (predicted UP)
  Entry Price:  $0.765
  Final Price:  $0.9985 (UP at expiry)
  Result:       ✓ WIN - Direction matched

Trade 2: KXBNB15M-26APR062045-45
  Entry Time:   2026-04-07 00:33:09 UTC  
  Entry Side:   YES (predicted UP)
  Entry Price:  $0.665
  Final Price:  $0.0055 (DOWN at expiry)
  Result:       ✗ LOSS - Direction NOT matched

--------------------------------------------------------------------------------
BREAKDOWN BY TYPE:
  UP→UP (YES correctly predicted UP):   1
  DOWN→DOWN (NO correctly predicted DOWN): 0
  UP→DOWN (YES incorrectly predicted):  1
  DOWN→UP (NO incorrectly predicted):   0

🎯 DIRECTION MATCH RATE: 1/2 = 50.0%

⚠️  PATTERNS & CAVEATS:
--------------------------------------------------------------------------------
1. VERY SMALL SAMPLE SIZE (only 2 trades reached expiry)
2. ALL off-hours trades that reached expiry were "YES" (UP) predictions
3. No "NO" (DOWN) predictions reached expiry during off-hours
4. 3 trades closed by trailing stop before expiry - direction unknown
5. The trailing stop is catching profits/losses before the 15-min expiry

📋 TRAILING STOP CLOSURES (Direction Unknown):
--------------------------------------------------------------------------------
1. KXSOL15M NO @ $0.375 → closed @ $0.26 (DOWN) - exited early
2. KXBTC15M NO @ $0.325 → closed @ $0.295 (DOWN) - exited early  
3. KXXRP15M NO @ $0.365 → closed @ $0.135 (DOWN) - exited early

================================================================================
