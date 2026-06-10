"""The Hub — the local-first control plane the organizations live in.

A thin layer over the engine: it runs real builds, persists run telemetry, and
serves Mission Control + Memory from real data (nothing mocked). Built
hosting-ready — execution already goes through the engine's Executor seam, and the
model/storage seams are swappable — so the same engine lifts into a hosted service
later without a rewrite.
"""
