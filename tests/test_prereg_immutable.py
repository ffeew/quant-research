"""Pre-registration files are immutable: every PREREG* file must keep the exact bytes it had in
the base commit (a866c23). The digests below were computed from that commit's blobs."""

from __future__ import annotations

import hashlib

import pytest

from quant_research.utils import config as qrc

BASE_SHA256 = {
    "research/carry/reports/PREREG-carry-buildout-DRAFT.md": "fb8ebdb9024caab3e81c1012f3fe624d13f9e6a340b8419044a55d39762ccc48",
    "research/close_vwap_accumulation/reports/PREREG.md": "93830f05b6cdccac23cd608d94a8520d0f0784912436011761332fb964d51d23",
    "research/iv_gap/reports/PREREG_v2.md": "d09348cd834f5109f52744d50b834ec721c12558798ce75b67479593d9c07a6d",
    "research/macro_event_studies/reports/PREREG_curve-slope-financials-vs-utilities.md": "0971e754884f42b2419f4a76f77cda0ba8e8f6a0cabb24b7048feecee9496c4d",
    "research/macro_event_studies/reports/PREREG_oil-shock-energy-vs-discretionary.md": "7efb09beb18b51267f9bec49e593095e85aa12f79b0081656714695e330fa57c",
    "research/macro_event_studies/reports/PREREG_vix-backwardation-spy-rebound.md": "56fdae19457acc95ea87231831ef533d8b12ef40e248586de0d755dbad88b022",
    "research/macro_exposure_diffusion/reports/PREREG.md": "21792594672c545f82a40fc9b510b49efe6d49423eb39a748dc2e6f6fabec310",
    "research/news_sentiment/reports/PREREG_sector_lm_5d.md": "a1ead5a33a395ed0015d4092e433702a5cbbafc607de56d8b9b0cc4e573eae63",
    "research/sentiment_returns/reports/PREREG_H2C_r3.md": "fec5e5834c3a67ff4a3ec962464ef9a5ed75dddf626afc8e905455bcadfe3bb8",
    "research/sentiment_returns/reports/PREREG_H3_v2.md": "b55eb6684c3b20b442895867d3f73e5cf490499877a4b127e595a50c807dd5a4",
    "research/sentiment_returns/reports/PREREG_v5.md": "d0e7658437eb04e94e61aa47b366d89acb79ac90d2d56fd4ac2bccdb0032d0c0",
    "research/sentiment_sector_switch/reports/PREREG_v0.4.md": "ed27b79c199d0c0e41499ad0d2c3ed104be1ac1a6da2d57f21a3a59c63d4f5fd",
    "research/statarb_bellwether/reports/PREREG_v3.md": "f3b2b1beeb95571934a32f11e141c177d51ac801c22ead0b0e3c0f5b397e4a1a",
    "research/trade_size_compression/reports/PREREG.md": "a1945f6e73aa61e1b989457dbe9f8f51871ec97cbdcfbaf7dbf5e74da85013a7",
    "research/treasury_bullet_barbell/reports/PREREG_v0.2.md": "7b79f21ef2e1f66ded85660bc2701311d6b078639c440de5abb3085d744f0cd8",
    "research/trend_tsmom/reports/PREREG-v2.md": "db90f920c1c4f23bf36c92bd41696d7e4ab4705bc37f47ee35050b3a31471bda",
    "research/trend_tsmom/reports/PREREG-v3.md": "7b14a2ac7e434adff08819f77973d2b174efaeffe8d408071b0370d267df143f",
    "research/vrp_iron_condor/reports/PREREG_v0.1.md": "330e4e20438bbbccbf7aa2cf68390931b80baef57351735dccab789616256fe6",
}


def test_prereg_set_is_unchanged() -> None:
    found = sorted(
        str(p.relative_to(qrc.REPO_ROOT)) for p in (qrc.REPO_ROOT / "research").rglob("PREREG*") if p.is_file()
    )
    assert found == sorted(BASE_SHA256)


@pytest.mark.parametrize("rel", sorted(BASE_SHA256))
def test_prereg_bytes_match_base(rel: str) -> None:
    assert hashlib.sha256((qrc.REPO_ROOT / rel).read_bytes()).hexdigest() == BASE_SHA256[rel], rel
