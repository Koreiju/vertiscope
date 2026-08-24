"""Experimental sweeps.

Permitted as a scanning/experimental module. These modules *produce and
record* measurements; they never *present* them. Presentation is the
REPL's job (`sweep`, `sweep watch`), because a surface that reports on a
running measurement has to read the record at the moment it is looked at.
A generated page is a snapshot, and one labelled "live" is a snapshot that
lies. See OBJECT_MODEL.md section 8.
"""
