import json
from datetime import datetime
from loguru import logger
import anthropic
from config.settings import settings

STRATEGY_RULES = """
You are COGNEX, an autonomous F&O options trading agent for Indian markets.
You trade on behalf of Kiran, an experienced options trader in Hyderabad.

=== APPROVED STRATEGIES ===

1. CALENDAR SPREAD — VIX < 15, range-bound, 3+ days to expiry
   Sell near-week expiry, buy next-week at same strike near MaxPain

2. HYBRID V2 — Trending market, VIX 13-18
   Multi-leg position with hedge, ATM +/- 1 strike based on trend

3. IRON FLY — IV rank > 65, sideways, near expiry
   Sell ATM CE + PE, buy OTM wings at MaxPain strike

4. DIRECTIONAL CE — Buy when: result beat, bullish macro, strong PE OI wall
   First OTM strike, Delta 0.35-0.45, Stop Loss 35% of premium

5. DIRECTIONAL PE — Buy when: result miss, USFDA warning, bearish sector
   First OTM strike, Delta 0.35-0.45, Stop Loss 35% of premium

6. STAY FLAT — VIX > 20, budget day, election day, unclear signal, expiry after 2:30pm

=== STOCK F&O RULES ===
Max 3 stock positions. Mandatory stop-loss on every buy.
Priority sectors: Banks, IT, Pharma, Energy, Auto
Trigger events: BSE result filing, USFDA action, RBI banking news

=== DECISION FORMAT — respond ONLY in this JSON ===
{
  "decision": "TRADE or WAIT or EXIT_EXISTING",
  "market_regime": "TRENDING_UP or TRENDING_DOWN or SIDEWAYS or HIGH_VIX or EVENT_DAY",
  "instrument": "NIFTY or BANKNIFTY or stock name or null",
  "strategy": "CALENDAR_SPREAD or HYBRID_V2 or IRON_FLY or DIRECTIONAL_CE or DIRECTIONAL_PE or null",
  "direction": "BUY or SELL or null",
  "option_type": "CE or PE or null",
  "suggested_strike": 24500 or null,
  "expiry": "weekly or monthly or null",
  "quantity_lots": 1 or null,
  "reasoning": "Clear explanation of WHY in 3-4 sentences",
  "confidence": "HIGH or MEDIUM or LOW",
  "risk_note": "Any specific risk or caution"
}
"""

class AgentBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.cycle_count = 0

    def make_decision(self, market_snapshot, news_text, current_positions, today_pnl):
        self.cycle_count += 1
        logger.info(f"Agent decision cycle #{self.cycle_count}")
        user_message = self._build_context(market_snapshot, news_text, current_positions, today_pnl)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=STRATEGY_RULES,
                messages=[{"role": "user", "content": user_message}]
            )
            raw_text = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens
            decision = self._parse_decision(raw_text)
            decision["tokens_used"] = tokens_used
            decision["model_used"] = self.model
            decision["cycle"] = self.cycle_count
            self._log_decision(decision, market_snapshot)
            logger.info(f"Decision: {decision.get('decision')} | Regime: {decision.get('market_regime')} | Tokens: {tokens_used}")
            return decision
        except Exception as e:
            logger.error(f"Agent brain error: {e}")
            return {"decision": "WAIT", "reasoning": f"Error: {e}", "confidence": "LOW"}

    def _build_context(self, snapshot, news, positions, today_pnl):
        nifty = snapshot.get("nifty", {})
        banknifty = snapshot.get("banknifty", {})
        now = datetime.now(settings.ist_timezone)
        return f"""
=== MARKET DATA ({now.strftime('%d-%b-%Y %H:%M IST')}) ===
NIFTY: Spot={nifty.get('spot','N/A')} PCR={nifty.get('pcr','N/A')} MaxPain={nifty.get('max_pain','N/A')} CE_Wall={nifty.get('ce_wall','N/A')} PE_Wall={nifty.get('pe_wall','N/A')}
BANKNIFTY: Spot={banknifty.get('spot','N/A')} PCR={banknifty.get('pcr','N/A')} MaxPain={banknifty.get('max_pain','N/A')}
VIX={snapshot.get('vix','N/A')} Crude=${snapshot.get('crude_oil','N/A')} USDINR=Rs{snapshot.get('usdinr','N/A')}
=== POSITIONS ({len(positions)} open) ===
{self._format_positions(positions)}
=== TODAY PnL ===
Net PnL: Rs{today_pnl:.2f} | Daily limit: Rs{settings.max_daily_loss_rs:.2f} | Remaining: Rs{settings.max_daily_loss_rs + today_pnl:.2f}
=== NEWS ===
{news}
Respond ONLY in the JSON format specified. No other text.
"""

    def _format_positions(self, positions):
        if not positions:
            return "No open positions"
        return "\n".join([f"  {p.get('symbol')} Qty:{p.get('quantity')} PnL:Rs{p.get('pnl',0):.2f}" for p in positions])

    def _parse_decision(self, raw_text):
        try:
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw_text[start:end])
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}")
        return {"decision": "WAIT", "market_regime": "UNKNOWN", "reasoning": "Could not parse response", "confidence": "LOW"}

    def _log_decision(self, decision, snapshot):
        try:
            from core.database import AgentDecision, SessionLocal
            db = SessionLocal()
            record = AgentDecision(
                cycle_number=self.cycle_count,
                market_regime=decision.get("market_regime", ""),
                nifty_spot=snapshot.get("nifty", {}).get("spot"),
                banknifty_spot=snapshot.get("banknifty", {}).get("spot"),
                vix=snapshot.get("vix"),
                pcr_nifty=snapshot.get("nifty", {}).get("pcr"),
                decision=decision.get("decision", ""),
                reasoning=decision.get("reasoning", ""),
                tokens_used=decision.get("tokens_used", 0),
                model_used=decision.get("model_used", ""),
            )
            db.add(record)
            db.commit()
            db.close()
        except Exception as e:
            logger.debug(f"Decision log error: {e}")

agent_brain = AgentBrain()
