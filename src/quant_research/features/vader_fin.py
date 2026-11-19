"""Pre-registered VADER scorer for the tradeable twins: vaderSentiment 3.3.2 with the finance-domain
neutralisation list lexicon/vader_finance_neutral_v1.txt (sha256 pinned below). Refuses to run on hash mismatch."""
import hashlib, os
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
HERE = os.path.dirname(os.path.abspath(__file__))
OVERRIDE = os.path.join(HERE, "lexicon", "vader_finance_neutral_v1.txt")
OVERRIDE_SHA = "4e1ff542f8f3b4f38c10839679637c6597c7fb9d61f66a8689f6952c945d7632"

def analyzer():
    if hashlib.sha256(open(OVERRIDE, "rb").read()).hexdigest() != OVERRIDE_SHA:
        raise RuntimeError("vader_finance_neutral_v1.txt hash mismatch")
    va = SentimentIntensityAnalyzer()
    words = [l.strip() for l in open(OVERRIDE) if l.strip() and not l.startswith("#")]
    removed = [w for w in words if va.lexicon.pop(w, None) is not None]
    va.removed = removed
    return va

if __name__ == "__main__":
    print("removed from VADER lexicon:", analyzer().removed)
