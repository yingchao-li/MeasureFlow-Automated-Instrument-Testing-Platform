"""MeasureFlow virtual instruments.

Three SCPI-over-TCP servers (signal generator, audio analyzer, device under test) share one
in-process :class:`mfsim.bench.Bench`.  Every measurement is computed from samples that were
really generated, filtered, distorted and analysed; nothing is looked up or randomised.

Everything here is simulated; nothing is certified for real hardware or medical devices.
"""

__version__ = "0.1.0"
