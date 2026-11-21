"""Scripted agents, as `mockllm` callables (D5, D27, design.md 6).

This is the only package that reads a task's patches, and no other harness, statistics or RL
module may import it (R4, tests/unit/test_import_boundary.py).
"""
