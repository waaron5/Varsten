"""Eval / replay harness (Track B).

The shadow-evaluation loop that proves a cheaper-model swap is safe on a route's
real traffic before it can be applied. Everything here runs off the request hot
path: the proxy taps a sampled copy of traffic into the replay corpus
(``capture``), and a worker (``runner``) replays it through a candidate model and
scores it (``scoring``) to produce an auditable verdict.
"""
