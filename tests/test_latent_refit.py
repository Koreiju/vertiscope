"""The global fit refits when the app is latent (G-129, 2026-10-10). Planted:
the old rule -- 2x growth only -- does not refit a quiet app at 1.3x."""

from vertiscope.obsidian.projector import latent_refit_due


def test_a_quiet_app_that_has_grown_refits():
    assert latent_refit_due(quiet_s=200, queued=0, chunks_now=130, fitted_chunks=100)


def test_not_while_diffs_stream_or_wait_or_without_growth():
    assert not latent_refit_due(quiet_s=30, queued=0, chunks_now=130, fitted_chunks=100)
    assert not latent_refit_due(quiet_s=200, queued=5, chunks_now=130, fitted_chunks=100)
    assert not latent_refit_due(quiet_s=200, queued=0, chunks_now=110, fitted_chunks=100)
    assert not latent_refit_due(quiet_s=200, queued=0, chunks_now=130, fitted_chunks=0)


def test_planted_the_2x_rule_alone_never_refits_a_quiet_app_at_1_3x():
    assert not latent_refit_due(quiet_s=200, queued=0, chunks_now=130, fitted_chunks=100, growth=2.0)
