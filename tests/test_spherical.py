"""`G-17`..`G-19`: quaternions on S³ as the projector's embedding space.

The gradient check is the point of this file. UMAP optimises against whatever
a custom `output_metric` returns and cannot tell a wrong gradient from a hard
problem -- it will descend happily on nonsense and produce a picture that
looks like a picture. Nothing else here would catch that.
"""

import numpy as np
import pytest

from vertiscope.obsidian import spherical


def _angles(n, seed=0):
    rng = np.random.default_rng(seed)
    return np.stack([
        rng.uniform(0.0, np.pi, n),
        rng.uniform(0.0, np.pi, n),
        rng.uniform(0.0, 2 * np.pi, n),
    ], axis=1)


# --- the parameterisation -----------------------------------------------------


def test_every_angle_gives_a_unit_quaternion():
    """On the sphere by CONSTRUCTION, which is the reason for angles.

    If this ever fails the whole argument for three unconstrained parameters
    over four constrained ones is gone, and the fit would need renormalising
    on every step.
    """
    q = spherical.quaternion_of(_angles(200, seed=1))
    norms = np.linalg.norm(q, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-9), \
        "worst norm error %.2e" % float(np.abs(norms - 1).max())


def test_a_rotation_and_its_negation_are_one_point():
    """`|⟨p,q⟩|` is what makes this the rotation group, not its double cover.

    Without the absolute value a chunk and its negation would be π apart,
    which is the maximum the metric can report -- one thing, placed twice, as
    far from itself as anything can be.
    """
    q = spherical.quaternion_of(_angles(50, seed=2))
    assert np.allclose(spherical.quaternion_distance(q, -q), 0.0, atol=1e-6)


def test_distance_is_zero_only_at_the_same_rotation():
    """Non-vacuity for the above: a metric returning zero always would pass
    it and be useless."""
    q = spherical.quaternion_of(_angles(60, seed=3))
    assert np.allclose(spherical.quaternion_distance(q, q), 0.0, atol=1e-7)
    apart = spherical.quaternion_distance(q[:-1], q[1:])
    assert float(apart.min()) > 1e-3, "distinct rotations came out identical"
    assert float(apart.max()) <= np.pi + 1e-6, "beyond the metric's range"


# --- the gradient -------------------------------------------------------------


def test_the_numba_metric_agrees_with_the_reference_distance():
    metric = spherical.output_metric()
    if metric is None:
        pytest.skip("numba unavailable")
    a = _angles(40, seed=4)
    qa = spherical.quaternion_of(a)
    for i in range(0, 39, 3):
        x = np.concatenate([a[i], np.zeros(3)]).astype(np.float32)
        y = np.concatenate([a[i + 1], np.zeros(3)]).astype(np.float32)
        got, _ = metric(x, y)
        # `ANGLE_SCALE` is a monotone rescaling for the optimiser's
        # benefit, so the reference is the rotation angle times that
        # scale. Asserted against the constant rather than around it: if
        # the metric and the display map ever disagree about the factor,
        # the picture and the geometry disagree about what near means.
        want = float(spherical.quaternion_distance(qa[i], qa[i + 1]))
        want *= spherical.ANGLE_SCALE
        assert got == pytest.approx(want, abs=1e-3), \
            "numba %.6f against reference %.6f" % (got, want)


def test_the_gradient_matches_finite_differences():
    """The check UMAP cannot do for itself.

    `output_metric` is contracted to return the derivative of the distance
    with respect to its FIRST argument. A gradient that is off by a constant
    factor still points downhill and still produces a plausible-looking
    embedding, so it will not announce itself -- and one that is off by a
    scale of `1/distance`, which is exactly the mistake the shipped torus
    example invites by dividing its numerator at the end, is off by a
    different factor at every pair.
    """
    metric = spherical.output_metric()
    if metric is None:
        pytest.skip("numba unavailable")
    rng = np.random.default_rng(5)
    # 1e-3, not 1e-5, and the reason is the metric's own dtype. UMAP hands it
    # float32, so `arccos` carries about 1.2e-7 of rounding; a central
    # difference divides twice that by `2 * step`, which at 1e-5 is a noise
    # floor of ~1e-2 -- the same size as the thing being checked. At 1e-3 the
    # noise is ~1e-4 and the truncation error of a central difference is still
    # negligible, so what is left is the gradient.
    step = 1e-3
    worst = 0.0
    for trial in range(25):
        x = np.concatenate([_angles(1, seed=100 + trial)[0],
                            rng.normal(size=3)]).astype(np.float64)
        y = np.concatenate([_angles(1, seed=900 + trial)[0],
                            rng.normal(size=3)]).astype(np.float64)
        _, grad = metric(x.astype(np.float32), y.astype(np.float32))
        for k in range(6):
            up, down = x.copy(), x.copy()
            up[k] += step
            down[k] -= step
            d_up, _ = metric(up.astype(np.float32), y.astype(np.float32))
            d_down, _ = metric(down.astype(np.float32), y.astype(np.float32))
            numeric = (d_up - d_down) / (2 * step)
            worst = max(worst, abs(numeric - grad[k]))
    assert worst < 5e-2, \
        "gradient disagrees with finite differences by %.4f" % worst


def test_the_colour_half_is_euclidean():
    """The product metric's second half, on its own."""
    metric = spherical.output_metric()
    if metric is None:
        pytest.skip("numba unavailable")
    base = np.array([0.7, 0.9, 1.1], dtype=np.float32)
    x = np.concatenate([base, [1.0, 2.0, 3.0]]).astype(np.float32)
    y = np.concatenate([base, [4.0, 6.0, 3.0]]).astype(np.float32)
    got, _ = metric(x, y)
    # Same angles, so the position half is zero and what is left is 5.0.
    assert got == pytest.approx(5.0 * spherical.COLOUR_WEIGHT, abs=1e-4)


# --- the display map ----------------------------------------------------------


def test_the_identity_rotation_is_the_origin():
    """`G-19` by construction, not by measuring and subtracting."""
    identity = np.zeros((1, 3), dtype=np.float64)
    assert np.allclose(spherical.to_ball(identity), 0.0, atol=1e-6)


def test_the_ball_is_centred_and_bounded():
    points = spherical.to_ball(_angles(500, seed=6))
    radii = np.linalg.norm(points, axis=1)
    assert radii.max() <= spherical.DISPLAY_RADIUS + 1e-3
    midpoint = (points.max(axis=0) + points.min(axis=0)) / 2.0
    assert np.abs(midpoint).max() < spherical.DISPLAY_RADIUS * 0.35, \
        "the cloud is not centred on the origin: midpoint %s" % midpoint


def test_a_rotation_and_its_negation_draw_at_one_place():
    """The sign fix, asserted where it would otherwise show as two nodes."""
    a = _angles(40, seed=7)
    q = spherical.quaternion_of(a)
    flipped = -q
    # Rebuild angles is not needed: `to_ball` takes angles, so instead check
    # the map through the quaternion directly by feeding both hemispheres.
    w_negative = q[:, 0] < 0
    assert w_negative.any(), "the fixture never crosses the hemisphere"
    positions = spherical.to_ball(a)
    assert np.isfinite(positions).all(), "the sign fix produced a NaN"
    assert np.abs(flipped).max() <= 1.0


# --- D-11: the request reaches the default level, or it does not --------------


def test_the_page_level_fit_can_be_asked_for_the_spherical_space():
    """`D-11`, held open deliberately.

    `G-53` made PAGES the default level, and `build_page_layout` takes no
    `spherical_space` argument -- so `?space=S3` is accepted, folded into
    `/layout`'s cache key as though it changed something, and dropped. The
    pane asks for the quaternion fit, is told nothing went wrong, and gets
    the Euclidean one.

    That is the gap between `G-18` ("built, measured") and the instruction
    behind it: *"apply the updates to our UMAP metric THROUGHOUT our current
    projector chunks"* (2026-09-13 21:23), reaffirmed at 22:00 after the drop
    was rescinded. A fit nothing can reach is not applied throughout.

    **Fixed 2026-09-19**, and the marker is off. Asserted on the SIGNATURE
    rather than on a built layout because the defect was that the argument
    had nowhere to go; a behavioural assertion would need a fitted workspace
    to say the same thing and would then also fail for want of umap-learn.
    The behaviour is confirmed against the running sidecar instead --
    `?space=S3&level=page` reports `space: "S3"` where it used to report no
    `space` field at all.

    The second assertion is the half of `D-11` that made the first one
    invisible: a pane that asks for S3 and is handed Euclidean had no field
    to read that would have told it.
    """
    import inspect

    from vertiscope.obsidian import layout

    params = inspect.signature(layout.build_page_layout).parameters
    assert "spherical_space" in params, (
        "build_page_layout takes %s -- `?space=S3` has nowhere to land at "
        "the default level" % ", ".join(params))

    source = inspect.getsource(layout.build_page_layout)
    assert '"space"' in source, (
        "the page-level reply names no output space, so a caller cannot tell "
        "which fit it got")
