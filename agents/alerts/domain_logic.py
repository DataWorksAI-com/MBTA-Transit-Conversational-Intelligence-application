"""
Alerts Domain Expertise - With Honest Assumptions
Version: 1.1 - Bug Fixes

TRANSPARENCY NOTE:
The delay duration patterns in this module are ESTIMATED RANGES based on:
- General transit operational knowledge
- Logical reasoning about incident types
- Industry standard patterns

These are NOT derived from MBTA historical data analysis.

In a production system, these would be replaced with:
- Historical MBTA alert resolution time analysis
- Machine learning models trained on past incidents
- Real-time pattern learning

The research contribution is the ARCHITECTURE that enables domain expertise,
demonstrated here with plausible assumptions.

FIXES in v1.1:
- Capped elapsed time at 180 minutes (filters out stale alerts)
- Fixed recommendation logic to respect individual alert recommendations
- Better overall assessment logic
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AlertsDomainExpert:
    """
    Domain expertise for MBTA service alerts.
    
    Demonstrates how agents can provide analysis beyond raw API data.
    Uses estimated patterns to show the architectural concept.
    """
    
    # ========================================================================
    # DELAY DURATION PATTERNS (ASSUMPTIONS)
    # 
    # These are ESTIMATED ranges demonstrating the pattern.
    # Based on logical reasoning:
    # - Signal/track problems take longer than passenger incidents
    # - Police actions have high variance
    # - Medical emergencies resolve relatively quickly
    #
    # SOURCE: Assumptions for architectural demonstration
    # CONFIDENCE: Low (0.5-0.7) - marked as estimates
    # ========================================================================
    
    DELAY_PATTERNS = {
        "signal_problem": {
            "min": 15,
            "max": 45,
            "severity": "major",
            "description": "Signal equipment malfunction",
            "note": "Estimated range - not from historical data"
        },
        "medical_emergency": {
            "min": 8,
            "max": 20,
            "severity": "moderate",
            "description": "Medical assistance required",
            "note": "Estimated range - not from historical data"
        },
        "police_action": {
            "min": 20,
            "max": 90,
            "severity": "critical",
            "description": "Police investigation",
            "note": "Estimated range - high variance"
        },
        "disabled_train": {
            "min": 10,
            "max": 30,
            "severity": "major",
            "description": "Mechanical failure",
            "note": "Estimated range - not from historical data"
        },
        "track_problem": {
            "min": 25,
            "max": 60,
            "severity": "critical",
            "description": "Track inspection/repair",
            "note": "Estimated range - not from historical data"
        }
    }
    
    def __init__(self):
        logger.info("=" * 80)
        logger.info("AlertsDomainExpert v1.1 initialized")
        logger.info("  NOTE: Using estimated delay patterns for demonstration")
        logger.info("  Production would use historical MBTA data")
        logger.info("=" * 80)
    
    def identify_cause(self, alert_text: str) -> Optional[str]:
        """Identify delay cause from alert text using pattern matching"""
        text_lower = alert_text.lower()
        
        if any(w in text_lower for w in ["signal", "signaling"]):
            return "signal_problem"
        elif any(w in text_lower for w in ["medical", "passenger"]):
            return "medical_emergency"
        elif any(w in text_lower for w in ["police", "investigation"]):
            return "police_action"
        elif any(w in text_lower for w in ["disabled", "mechanical"]):
            return "disabled_train"
        elif any(w in text_lower for w in ["track", "rail"]):
            return "track_problem"
        
        return None
    
    def predict_duration(self, cause: Optional[str]) -> Dict[str, Any]:
        """
        Predict delay duration based on cause.
        Returns prediction with LOW confidence to indicate estimates.
        """
        if not cause or cause not in self.DELAY_PATTERNS:
            return {
                "prediction": "duration unknown",
                "severity": "unknown",
                "confidence": 0.2
            }
        
        pattern = self.DELAY_PATTERNS[cause]
        return {
            "prediction": f"{pattern['min']}-{pattern['max']} minutes",
            "min": pattern["min"],
            "max": pattern["max"],
            "severity": pattern["severity"],
            "confidence": 0.6,  # Low confidence = honest about estimates
            "note": pattern["note"]
        }
    
    def calculate_elapsed(self, created_at: str) -> Optional[int]:
        """
        Calculate minutes since alert created.
        
        FIXED in v1.1: Caps at 180 minutes to filter out stale/long-term alerts.
        Long-term service changes (construction, etc.) shouldn't be treated
        as active delays for prediction purposes.
        """
        if not created_at:
            return None
        
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            elapsed = datetime.now(created.tzinfo) - created
            minutes = int(elapsed.total_seconds() / 60)
            
            # Cap at 180 minutes (3 hours)
            # Alerts older than this are likely long-term service changes,
            # not active incidents suitable for short-term prediction
            if minutes > 180:
                logger.info(f"⚠️ Alert is {minutes} minutes old, capping at 180 (stale alert)")
                return 180
            
            return minutes
        except Exception as e:
            logger.error(f"Error calculating elapsed time: {e}")
            return None
    
    def determine_status(self, elapsed: Optional[int], alert_text: str) -> str:
        """
        Determine current delay status.
        Uses simple heuristics based on time elapsed.
        """
        text_lower = alert_text.lower()
        
        # Check for explicit indicators
        if any(w in text_lower for w in ["resolving", "clearing", "resuming", "restored"]):
            return "resolving"
        
        if elapsed is None:
            return "ongoing"
        
        # Very long elapsed (near cap) = treat as ongoing long-term issue
        if elapsed >= 180:
            return "ongoing"  # Not "extended" - it's a long-term service change
        
        if elapsed < 10:
            return "just_started"
        elif elapsed > 45:
            return "extended"
        else:
            return "ongoing"
    
    def recommend_action(
        self,
        status: str,
        severity: str,
        elapsed: Optional[int]
    ) -> Dict[str, str]:
        """Generate actionable recommendation"""
        
        # Long-term alerts (capped at 180) = ongoing service change, not acute delay
        if elapsed and elapsed >= 180:
            return {
                "action": "monitor",
                "reasoning": "Long-term service change - check current status before traveling"
            }
        
        if severity == "critical":
            return {
                "action": "take_alternative",
                "reasoning": "Critical disruption with extended duration expected"
            }
        
        if status == "resolving":
            return {
                "action": "wait",
                "reasoning": "Service returning to normal operations"
            }
        
        if status == "extended":
            return {
                "action": "take_alternative",
                "reasoning": "Delay exceeding typical resolution time"
            }
        
        if elapsed and elapsed > 20:
            return {
                "action": "consider_alternative",
                "reasoning": f"Delay ongoing for {elapsed} minutes"
            }
        
        if status == "just_started":
            return {
                "action": "monitor",
                "reasoning": "Recent disruption, situation developing"
            }
        
        return {
            "action": "monitor",
            "reasoning": "Delay within expected range"
        }
    
    def extract_routes_from_alert(self, alert: Dict[str, Any]) -> List[str]:
        """Extract affected routes from alert"""
        attrs = alert.get("attributes", {})
        informed_entity = attrs.get("informed_entity", [])
        
        routes = []
        for entity in informed_entity:
            if entity.get("route"):
                routes.append(entity["route"])
        
        return list(set(routes))
    
    def analyze_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full domain analysis of single alert.
        """
        attrs = alert.get("attributes", {})
        alert_text = f"{attrs.get('header', '')} {attrs.get('description', '')}"
        created_at = attrs.get("created_at")
        
        # Apply domain expertise
        cause = self.identify_cause(alert_text)
        prediction = self.predict_duration(cause)
        elapsed = self.calculate_elapsed(created_at)
        status = self.determine_status(elapsed, alert_text)
        recommendation = self.recommend_action(status, prediction["severity"], elapsed)
        routes = self.extract_routes_from_alert(alert)
        
        return {
            "alert_id": alert.get("id"),
            "alert_text": alert_text[:150],
            "cause": cause,
            "predicted_duration": prediction["prediction"],
            "severity": prediction["severity"],
            "elapsed_minutes": elapsed,
            "status": status,
            "recommendation": recommendation["action"],
            "reasoning": recommendation["reasoning"],
            "routes": routes
        }
    
    def analyze_multiple_alerts(
        self,
        alerts: List[Dict[str, Any]],
        route_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze multiple alerts and provide overall assessment.
        
        FIXED in v1.1: Better overall recommendation logic that respects
        individual alert recommendations.
        
        Args:
            alerts: List of alert dicts from MBTA API
            route_filter: Optional route filter (e.g. "Red") for context
        
        Returns:
            Overall analysis with recommendations
        """
        
        if not alerts:
            return {
                "total_alerts": 0,
                "critical_count": 0,
                "major_count": 0,
                "analyses": [],
                "overall_recommendation": "proceed_normally",
                "affected_routes": [],
                "summary": "No active disruptions"
            }
        
        # Analyze each alert
        analyses = [self.analyze_alert(a) for a in alerts]
        
        # Count by severity
        critical = sum(1 for a in analyses if a["severity"] == "critical")
        major = sum(1 for a in analyses if a["severity"] == "major")
        
        # FIXED: Count recommendations
        take_alt = sum(1 for a in analyses if a["recommendation"] == "take_alternative")
        consider_alt = sum(1 for a in analyses if a["recommendation"] == "consider_alternative")
        
        # Collect affected routes
        all_routes = []
        for analysis in analyses:
            all_routes.extend(analysis.get("routes", []))
        affected_routes = list(set(all_routes))
        
        # FIXED: Overall recommendation based on individual recommendations
        if take_alt > 0 or critical > 0:
            overall = "take_alternative"
            summary = f"{critical if critical > 0 else take_alt} critical/major disruption(s)"
        elif consider_alt > 0 or major >= 2:
            overall = "consider_alternative"
            summary = f"{major} major disruptions"
        elif major == 1:
            overall = "monitor"
            summary = "One major disruption"
        else:
            overall = "proceed_with_caution"
            summary = "Minor delays detected"
        
        return {
            "total_alerts": len(alerts),
            "critical_count": critical,
            "major_count": major,
            "analyses": analyses,
            "overall_recommendation": overall,
            "affected_routes": affected_routes,
            "summary": summary
        }
    
    def format_analysis_for_user(self, analysis: Dict[str, Any]) -> str:
        """Format single alert analysis for user display"""
        
        status_emoji = {
            "just_started": "🆕",
            "ongoing": "⏳",
            "resolving": "✅",
            "extended": "⚠️"
        }
        
        rec_emoji = {
            "wait": "⏱️",
            "take_alternative": "🚍",
            "consider_alternative": "🤔",
            "monitor": "👀"
        }
        
        lines = []
        lines.append(f"{status_emoji.get(analysis['status'], 'ℹ️')} **Status:** {analysis['status'].replace('_', ' ').title()}")
        
        if analysis["cause"]:
            lines.append(f"**Cause:** {analysis['cause'].replace('_', ' ').title()}")
            lines.append(f"**Typical Duration:** {analysis['predicted_duration']}")
        
        if analysis["elapsed_minutes"]:
            # Display capped time with note if it's at the cap
            elapsed = analysis["elapsed_minutes"]
            if elapsed >= 180:
                lines.append(f"**Elapsed:** 180+ minutes (long-term service change)")
            else:
                lines.append(f"**Elapsed:** {elapsed} minutes")
        
        lines.append("")
        lines.append(f"{rec_emoji.get(analysis['recommendation'], 'ℹ️')} **Recommendation:** {analysis['recommendation'].replace('_', ' ').title()}")
        lines.append(f"   {analysis['reasoning']}")
        
        return "\n".join(lines)