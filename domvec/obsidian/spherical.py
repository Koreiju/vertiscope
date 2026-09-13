"""The projector's embedding space: quaternions on S³ (`G-17`..`G-19`).

The goal, verbatim: *"for our UMAP, we'll use spherical/quaternion coordinates
and quaternion distances between points where we center our focus on the
origin."*

**Three angles, not four coordinates, and that is umap-learn's own advice.**
The docs are explicit that a custom output space should be "parameterized
without coordinate constraints to prevent issues during gradient descent",
which is why the shipped spherical metric is `haversine` over latitude and
longitude rather than over constrained 3-vectors. Optimising four numbers and
renormalising them to the unit 3-sphere on every step fights the optimiser;
optimising three unconstrained angles that GENERATE a unit quaternion does
not. The point is on S³ by construction, at every step, with no projection.

    q(φ) = ( cos φ₁,
             sin φ₁ cos φ₂,
             sin φ₁ sin φ₂ cos φ₃,
             sin φ₁ sin φ₂ sin φ₃ )

**The distance is the rotation angle, and the absolute value is load-bearing.**
`2·arccos(|⟨p,q⟩|)`: a unit quaternion and its negation are the same rotation,
so a metric that told them apart would place one thing in two places and
report the distance between them as π. Taking the absolute inner product is
what makes the space the rotation group rather than the sphere that double
covers it.

**Colour rides along, Euclidean.** The fit is six components: three angles for
position and three ordinary coordinates for hue, saturation and value, under a
product metric. That keeps the property the previous design was built for --
"the colour has to come from the same projection as the position or it is a
second, unrelated picture painted on top of the first" -- while position moves
to the sphere. A product of two metrics is a metric, so nothing about UMAP's
assumptions changes.

**Centred on the origin** (`G-19`) by the map at the bottom of this file. The
identity quaternion goes to the origin and the rotation angle becomes the
radius, so the cloud is a ball about the origin and the camera cannot end up
inside it -- the failure `graph.ts` records, a camera at z = −230 inside a
cloud spanning ±249.
"""

from __future__ import annotations

import numpy as np

#: How much the colour half of the product metric counts against the position
#: half.
#:
#: One, which is a starting point and not a finding. The two halves are in
#: different units -- radians of rotation against unconstrained coordinates --
#: so there is no scale at which they are obviously commensurate, and this is
#: the knob to sweep when there is a measurement to sweep it against. It is
#: named rather than inlined for exactly that reason.
COLOUR_WEIGHT = 1.0

#: The radius of the ball the sphere is drawn in.
DISPLAY_RADIUS = 300.0

#: What the rotation angle is multiplied by before UMAP optimises against it.
#:
#: A MONOTONE rescaling, so it changes nothing about which points are near
#: which -- it changes the range the optimiser works in. `2·arccos(|⟨p,q⟩|)`
#: is bounded by π, and UMAP's low-dimensional `a`/`b` curve is fitted for
#: unbounded Euclidean distances at the given `min_dist`; handed a metric
#: whose entire range is 0 to 3.14 it has no room to separate anything, and
#: the fit saturates near zero. Measured on the 4,985-node corpus at scale 1:
#: a median radius of 10.8 out of 300 and retention 0.188 against the
#: Euclidean fit's 0.375.
ANGLE_SCALE = 8.0


def quaternion_of(angles: np.ndarray) -> np.ndarray:
    """Hyperspherical angles -> unit quaternions, rows at a time.

    The inverse of nothing in particular: the angles are what UMAP optimises
    and this is how they become a point. Unit by construction, which is the
    whole reason for parameterising this way.
    """
    a = np.asarray(angles, dtype=np.float64)
    p1, p2, p3 = a[:, 0], a[:, 1], a[:, 2]
    s1 = np.sin(p1)
    s2 = np.sin(p2)
    return np.stack([
        np.cos(p1),
        s1 * np.cos(p2),
        s1 * s2 * np.cos(p3),
        s1 * s2 * np.sin(p3),
    ], axis=1)


def quaternion_distance(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """`2·arccos(|⟨p,q⟩|)`, the angle between two rotations.

    The reference implementation, in numpy, for the tests to check the numba
    one against. A metric written twice and compared is a metric that has been
    read twice; the fast one alone would be a claim nobody verified.
    """
    dot = np.abs(np.sum(np.asarray(p) * np.asarray(q), axis=-1))
    return 2.0 * np.arccos(np.clip(dot, -1.0, 1.0))


def _build_metric(colour_weight: float):
    """The numba `output_metric` UMAP optimises against.

    Built rather than written at module level so the colour weight is captured
    as a constant -- numba closes over it at compile time, and a global read
    per distance evaluation is a cost paid a hundred million times in a fit.

    Returns ``(distance, gradient)`` where the gradient is with respect to the
    FIRST argument, which is umap-learn's contract -- the true derivative, not
    a direction. See the note above the return for why this does NOT copy the
    shipped torus example's trailing division.
    """
    import numba

    weight = float(colour_weight)
    angle_scale = float(ANGLE_SCALE)

    @numba.njit(fastmath=True)
    def spherical_grad(x, y):                       # pragma: no cover - numba
        # --- position: the rotation angle between the two quaternions ------
        c1x, s1x = np.cos(x[0]), np.sin(x[0])
        c2x, s2x = np.cos(x[1]), np.sin(x[1])
        c3x, s3x = np.cos(x[2]), np.sin(x[2])
        c1y, s1y = np.cos(y[0]), np.sin(y[0])
        c2y, s2y = np.cos(y[1]), np.sin(y[1])
        c3y, s3y = np.cos(y[2]), np.sin(y[2])

        qx0, qx1 = c1x, s1x * c2x
        qx2, qx3 = s1x * s2x * c3x, s1x * s2x * s3x
        qy0, qy1 = c1y, s1y * c2y
        qy2, qy3 = s1y * s2y * c3y, s1y * s2y * s3y

        dot = qx0 * qy0 + qx1 * qy1 + qx2 * qy2 + qx3 * qy3
        sign = 1.0 if dot >= 0.0 else -1.0
        adot = dot * sign
        if adot > 1.0:
            adot = 1.0
        angle = angle_scale * 2.0 * np.arccos(adot)

        # d/dφ of the quaternion, then chain through `2·arccos`.
        #
        # dq/dφ₁
        g0 = (-s1x) * qy0 + (c1x * c2x) * qy1 \
            + (c1x * s2x * c3x) * qy2 + (c1x * s2x * s3x) * qy3
        # dq/dφ₂
        g1 = (s1x * -s2x) * qy1 + (s1x * c2x * c3x) * qy2 \
            + (s1x * c2x * s3x) * qy3
        # dq/dφ₃
        g2 = (s1x * s2x * -s3x) * qy2 + (s1x * s2x * c3x) * qy3

        # d(angle)/d(dot) = -2·sign / sqrt(1 - dot²), guarded where the two
        # points coincide and the derivative is genuinely undefined.
        denom = np.sqrt(1.0 - adot * adot)
        if denom < 1e-9:
            denom = 1e-9
        scale = -angle_scale * 2.0 * sign / denom

        grad = np.zeros(x.shape[0], dtype=np.float32)
        grad[0] = scale * g0
        grad[1] = scale * g1
        grad[2] = scale * g2

        # --- colour: ordinary Euclidean, on whatever dimensions remain -----
        colour_sq = 0.0
        for i in range(3, x.shape[0]):
            d = x[i] - y[i]
            colour_sq += d * d
        colour = np.sqrt(colour_sq)
        if colour > 1e-12:
            for i in range(3, x.shape[0]):
                grad[i] = weight * (x[i] - y[i]) / colour

        total = angle + weight * colour
        # NOT divided by the distance, and that is a correction rather than a
        # style. The shipped torus example ends `return distance, g/(1e-6 +
        # distance)`, which reads like a convention and is not one: there `g`
        # holds `(x-y)`, the unnormalised numerator, and dividing by the
        # distance is what turns it into the derivative. Everything assembled
        # above is already the derivative, so dividing again would scale it by
        # `1/distance` -- a different wrong factor at every pair, still
        # pointing downhill, still producing a plausible-looking embedding.
        # The finite-difference test is what found it: 1.56 off.
        return total, grad

    return spherical_grad


def output_metric(colour_weight: float = COLOUR_WEIGHT):
    """The metric to hand UMAP's `output_metric`, or None when numba is gone.

    Returning None rather than raising: a workspace without numba should still
    get a picture, and the caller reports which space it actually fitted --
    the same rule every other field in the layout report follows.
    """
    try:
        return _build_metric(colour_weight)
    except Exception:                               # noqa: BLE001
        return None


def to_ball(angles: np.ndarray, radius: float = DISPLAY_RADIUS) -> np.ndarray:
    """S³ -> a ball about the origin, for a camera to look at (`G-19`).

    The logarithmic map of the rotation group: a quaternion becomes an axis
    and an angle, and the point is that axis scaled by that angle. The
    identity rotation lands exactly on the origin, so the cloud is centred by
    construction rather than by measuring its extent and subtracting -- which
    is what `G-19` asks for and what makes `recentre` unnecessary.

    **The sign is fixed first, and it has to be.** `q` and `−q` are one
    rotation; mapping them separately would put one chunk at two antipodal
    places. Forcing `w ≥ 0` picks the representative on the near hemisphere,
    which is the same choice the absolute value in the metric makes.

    Angle, not chord: the radius is the rotation angle, so a point's distance
    from the origin means the same thing the metric means. Distances between
    two points off the origin compress as they approach the boundary, which is
    what a log map does and is stated rather than hidden -- the alternative is
    a picture whose radius is not any quantity the fit optimised.
    """
    q = quaternion_of(angles)
    # Sign-normalise onto w >= 0.
    flip = np.where(q[:, 0] < 0.0, -1.0, 1.0)[:, None]
    q = q * flip

    w = np.clip(q[:, 0], -1.0, 1.0)
    theta = 2.0 * np.arccos(w)                      # the rotation angle
    axis = q[:, 1:]
    norm = np.linalg.norm(axis, axis=1, keepdims=True)
    # At the identity the axis is undefined and the angle is zero, so any
    # direction gives the same point: the origin. Guarding the divide keeps
    # that from becoming a NaN that would propagate into every coordinate.
    norm[norm < 1e-12] = 1.0
    unit = axis / norm
    return (unit * (theta / np.pi)[:, None] * radius).astype(np.float32)


def from_ball(points: np.ndarray, radius: float = DISPLAY_RADIUS
              ) -> np.ndarray:
    """The inverse of :func:`to_ball`: a position -> the angles that draw it.

    Used to WARM START the spherical fit from a Euclidean one. Left to its own
    initialisation the fit collapses onto the identity rotation -- measured on
    the 4,985-node corpus, a median radius of 10.8 out of 300 and
    neighbourhood retention of 0.188 against the Euclidean fit's 0.375 -- and
    the colour weight is not the cause, since 1.0 and 0.1 give 0.188 and
    0.189. What is left is the parameterisation: hyperspherical angles are
    singular at φ₁ = 0 and φ₂ = 0, exactly where the identity sits, and a fit
    that starts near there optimises in coordinates whose gradients are
    ill-conditioned.

    Starting from a layout that already has structure puts the points away
    from the singularity before the first step.
    """
    p = np.asarray(points, dtype=np.float64)
    norm = np.linalg.norm(p, axis=1, keepdims=True)
    safe = np.where(norm < 1e-12, 1.0, norm)
    axis = p / safe
    theta = np.clip(norm[:, 0] / radius, 0.0, 1.0) * np.pi
    half = theta / 2.0
    q = np.stack([np.cos(half),
                  np.sin(half) * axis[:, 0],
                  np.sin(half) * axis[:, 1],
                  np.sin(half) * axis[:, 2]], axis=1)

    phi1 = np.arccos(np.clip(q[:, 0], -1.0, 1.0))
    s1 = np.sin(phi1)
    s1 = np.where(np.abs(s1) < 1e-9, 1e-9, s1)
    phi2 = np.arccos(np.clip(q[:, 1] / s1, -1.0, 1.0))
    phi3 = np.arctan2(q[:, 3], q[:, 2])
    return np.stack([phi1, phi2, phi3], axis=1).astype(np.float32)
