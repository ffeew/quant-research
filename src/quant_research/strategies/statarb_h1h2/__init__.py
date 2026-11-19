"""Statarb H1/H2 harness: bellwether lag (H1) and earnings peer read-through (H2).

Config-driven port of the pre-registered runner. Every input path and sha256 pin comes from a
TOML config (see ``configs/statarb_h1h2.toml``) or the environment; nothing is hard-coded.
The harness fails closed: any missing/PENDING pin, sha mismatch, or row past the stage's
read-time end date stops the run before data is parsed or a return is computed.
"""
