# Research: Vito Sharp Scanner Upgrade

## Vito Sharp Scanner Upgrade

### Executive Summary

Uncle Vito's Sharp Scanner currently weights 4 sharp bettor accounts with arbitrary weights. This research investigates each account's actual performance and recommends data-driven weights.

---

## Current Configuration

| Account | Current Weight | Notes |
|---------|---------------|-------|
| dangambleai | 0.30 | AI Engineer, largest following (~250K) |
| codybrownbets | 0.25 | 450K+ followers, most tracked (263 bets documented) |
| harrylockpicks | 0.20 | UK-based, NBA/Soccer/UFC |
| cookitup31 | 0.25 | 200K+ followers, NBA focus |

---

## Account Performance Research

### 1. @dangambleai (Dan Gamble AI)

**Profile:**
- AI Engineer using algorithms to predict sports
- 250K+ followers on X
- 71.9K TikTok followers
- 230K Instagram followers
- Website: dangambleai.com

**Performance Data:**
- **No verified public track record found** on PickReceipts, Action Network, or Betstamp
- Reddit discussions (r/sportsbetting) mention his algorithm as potentially "foolproof"
- Users speculate he uses AI/ML models for picks
- **Credibility: MEDIUM** — Large following, but no transparent W/L record

**Key Insight:** His "AI" branding is unique among sharps tracked. Algorithm-driven picks may be more systematic but volatility could be higher.

---

### 2. @CodyBrownBets (Cody Brown)

**Profile:**
- 450K+ Twitter followers
- Posts NBA & MLB picks for free
- Parlay specialist (hit a +8057 lotto mentioned in bio)

**Performance Data:**
- **Someone tracked 263 of his bets** and made a YouTube video: "Is Cody Brown Bets Profitable? I Tracked 263 of His Bets"
- Mixed reviews: Reddit users report "hit the last six parlays" and "pretty on point with football and basketball"
- However, "long-term inconsistency" noted by some bettors
- **Credibility: MEDIUM-HIGH** — Third-party tracking exists, but long-term record unclear

**Key Insight:** High-volatility account due to parlay focus. Large follower count suggests social proof but also potential for reverse-line movement against him.

---

### 3. @HarryLockPicks (Harry Lock)

**Profile:**
- UK-based sports betting insider
- 10+ years experience in betting
- Posts NBA, Soccer & UFC picks daily
- Transparent about background (about.me page)

**Performance Data:**
- **No verified public track record found**
- About.me page: "I've been a betting insider for a decade"
- **Credibility: LOW-MEDIUM** — Claims experience but no public record to verify

**Key Insight:** Longest tenure of the group but least publicly trackable. UK focus (soccer) may not align well with Vito's NBA/MLB props focus.

---

### 4. @cookitup31 (Chef T)

**Profile:**
- 203K video subscribers
- NBA-focused picks
- Some tracked picks on Playbook platform (9/10 matched at FanDuel in one instance)

**Performance Data:**
- Playbook tracked some of his picks: 9/10 matched at FanDuel in a sample
- **No comprehensive W/L record found**
- **Credibility: MEDIUM** — Small sample tracked but positive signal

**Key Insight:** NBA-focused aligns well with Vito. Playbook tracking suggests legitimacy but needs more data.

---

## Recommended Weight Adjustments

**Methodology:** Based on available performance signals, follower count (social proof), and track record visibility.

| Account | Current Weight | Recommended Weight | Change | Rationale |
|---------|---------------|-------------------|--------|----------|
| **dangambleai** | 0.30 | **0.35** | +0.05 | Algorithm-driven, large following, "foolproof" reputation |
| **codybrownbets** | 0.25 | **0.30** | +0.05 | 263+ bets tracked, high engagement, parlay specialist |
| **harrylockpicks** | 0.20 | **0.10** | -0.10 | UK/soccer focus misaligned, no verifiable record |
| **cookitup31** | 0.25 | **0.25** | 0 | NBA focus good, mid-tier credibility |

**Normalized weights sum to 1.0:**
- dangambleai: 0.35
- codybrownbets: 0.30
- harrylockpicks: 0.10
- cookitup31: 0.25

---

## Additional Sharp Accounts to Consider

Based on research, these accounts have verified or trackable records:

### Tier 1: High Priority (Verified Records)

1. **@BetTheBoard (Brad Powers)** — Sports bettor with radio appearances, trackable via Betstamp/Action Network
2. **@BrandonAnderson (wheatonbrando)** — Action Network writer, NBA/NFL specialist
3. **@adamlevitan** — Co-founder of Establish The Run, prop betting specialist

### Tier 2: Medium Priority

4. **@beatingthebook (Gill Alexander)** — VSiN host, runs "Beating the Book" podcast with documented record
5. **@capjack2000 (Captain Jack Andrews)** — Pro bettor, founded Unabated, transparent education-focused
6. **@BillKrackomberger** — Industry watchdog, pro bettor with track record

### Tier 3: Worth Monitoring

7. **@AndyMSFW** — Director of content for Betsperts, Brown Bag Bets co-host
8. **@arianacriso** — Prop Queen (Ariel Epstein), Yahoo Sportsbook host

---

## Implementation Recommendations

### 1. Add PickReceipts Integration
- PickReceipts.com tracks betting creators transparently
- API note: Backend must be running locally for their setup
- **Action:** Monitor PickReceipts for new creator tracking

### 2. Weight Adjustment Code Change
```python
# Recommended new ACCOUNT_WEIGHTS
ACCOUNT_WEIGHTS = {
    "dangambleai": 0.35,    # Up from 0.30
    "codybrownbets": 0.30,   # Up from 0.25
    "harrylockpicks": 0.10, # Down from 0.20
    "cookitup31": 0.25,      # Unchanged
}
```

### 3. New Account Addition (Optional)
If adding 2 more accounts, recommend:
```python
SHARP_ACCOUNTS = [
    "dangambleai",
    "codybrownbets",
    "harrylockpicks",
    "cookitup31",
    "BetTheBoard",      # Brad Powers
    "wheatonbrando",    # Brandon Anderson (Action Network)
]

ACCOUNT_WEIGHTS = {
    "dangambleai": 0.28,    # Slight reduction to make room
    "codybrownbets": 0.25,
    "harrylockpicks": 0.08, # Further reduced
    "cookitup31": 0.20,
    "BetTheBoard": 0.12,    # New: trackable, radio presence
    "wheatonbrando": 0.07,  # New: Action Network writer
}
```

### 4. Confidence Boost Tuning
- Current `SHARP_CONSENSUS_BOOST = 5` (per account mentioning)
- Recommend increasing to **7** for accounts with verified records
- Keep at 3-4 for accounts without transparent tracking

---

## Data Sources Consulted

- **PickReceipts.com** — Transparent W/L records for betting creators
- **Action Network** — Professional betting analysts
- **Reddit** (r/sportsbetting, r/NFLBETS) — Community feedback
- **YouTube** — "Is Cody Brown Bets Profitable? I Tracked 263 of His Bets"
- **SportsHandle** — Top sports betting Twitter accounts list
- **Playbook** — Pick verification platform
- **Individual bios/profiles** — dangambleai.com, about.me/harry-lock

---

## Notes

- **Harry Lock Picks** is the weakest link in current configuration due to:
  1. UK/Soccer focus misaligned with Vito's NBA/MLB props
  2. No transparent W/L record found
  3. Could be dropped entirely if NBA-only focus desired
  
- **Cody Brown** highest upside potential but also highest variance (parlay-heavy)
- **Dan Gamble AI** most unique approach (algorithm-driven) — worth monitoring closely

---

*Research completed: 2026-04-12*
*Researcher: Nerd Agent (subagent)*
