# TEAM.md - Yonti Organization

## Executive
- **Tony (tbruno94):** CEO, project owner, decision maker
- **Jenkins (Me):** CSO, orchestrator, strategy, coordinator

## Operations

### Engineering
- **Pixel:** Lead coder. Builds all systems, scripts, bots. Does NOT make strategy decisions.

### Research
- **Nerd:** Researcher. Analyzes markets, finds patterns, improves strategies. Does NOT code.

### Market Intelligence  
- **Searcher Bot:** Finds active markets on Kalshi. Logs to file, not Discord.

### Trading (Execution Layer)
- **Super Bot:** Kalshi 15-minute crypto binary trading bot
  - max_bet: $2.00
  - balance_floor: $3.00 (auto-reset to $100)
  - Strategies: DEEP BUY, DRIFT BUY, DRIFT SHORT
  - Kelly Criterion with dynamic sizing based on cash available

### Reporting
- **Vito:** Sports betting report (🍝 NBA props, parlays)
- **Superbot Paper Report:** Balance, positions, P&L

## Reports (Every 15 min :00/:15/:30/:45)
1. Superbot Paper Report → Discord webhook
2. Vito Betting Report → Discord webhook
3. Scanner → logs to file locally

## Project State (April 1, 2026)
- Workspace was RESET tonight - everything wiped
- Superbot, Vito, Scanner need to be REBUILT
- Priority: Rebuild report posting system first
- Then rebuild Superbot trading system
