"""
Math functions
"""
import warnings

import numpy as np
from scipy import linalg
from numba import jit
from scipy.linalg import svd

MIN_EXP = -20
MAX_EXP = 20


def rectlin(x):
    """
    rectangular linear link

    Args:
        x: linear predictor
    """
    return x.clip(0, np.inf)


@jit
def sexp(x):
    """
    truncated exp

    Args:
        x: linear predictor
    """
    return np.exp(np.clip(x, MIN_EXP, MAX_EXP))


def identity(x):
    """
    identity link

    Args:
        x: linear predictor
    """
    return x


def log1exp(x):
    """
    log(1 + exp(x))

    Args:
        x: linear predictor
    """
    return np.log1p(np.exp(x))


def ichol_gauss(n, omega, r, tol=1e-6):
    """
    Incomplete Cholesky factorization of squared exponential covariance

    K \approx GG'

    Args:
        n: size of covariance matrix
        omega: inverse of 2 * squared lengthscale
        r: rank of factorization
        tol: tolerance of convergence

    Returns:
        incomplete lower trianglar matrix (n, r)
    """

    x = np.arange(n)
    diag = np.ones(n, dtype=float)
    pvec = np.arange(n, dtype=int)
    i = 0
    G = np.zeros((n, r), dtype=float)
    while i < r and np.sum(diag[i:]) > tol * n:
        if i > 0:
            jast = diag[i:].argmax()
            jast += i
            # Be caseful! numpy indexing returns a view instead of a copy.
            pvec[i], pvec[jast] = pvec[jast].copy(), pvec[i].copy()
            G[jast, :i + 1], G[i, :i + 1] = G[i, :i + 1].copy(), G[jast, :i + 1].copy()
        else:
            jast = 0

        G[i, i] = np.sqrt(diag[jast])
        nextcol = np.exp(- omega * (x[pvec[i + 1:]] - x[pvec[i]]) ** 2)
        G[i + 1:, i] = (nextcol - G[i + 1:, :i] @ G[i, :i].T) / G[i, i]
        diag[i + 1:] = 1 - np.sum((G[i + 1:, :i + 1]) ** 2, axis=1)

        i += 1
    if i == r:
        warnings.warn('Not enough rank')
    return G[pvec.argsort(), :]


def ichol(a, tol=1e-6):
    """
    Incomplete Cholesky factorization

    This version allows zero diagonal elements.
    The direct implementation of the version in wikipedia,
    https://en.wikipedia.org/wiki/Incomplete_Cholesky_factorization,
    encounters divided by zero.

    Args:
        a: square matrix
        tol: tolerance of zero

    Returns:
        incomplete lower trianglar matrix
    """

    n = a.shape[0]
    diag = a.diagonal().copy()  # Don't forget copy. diagonal() returns a read-only vector.
    pvec = np.arange(n, dtype=int)
    i = 0
    G = np.zeros((n, n), dtype=float)
    while i < n and np.sum(diag[i:]) > tol:
        if i > 0:
            jast = diag[i:].argmax()
            jast += i
            # Be caseful! numpy indexing returns a view instead of a copy.
            pvec[i], pvec[jast] = pvec[jast].copy(), pvec[i].copy()
            G[jast, :i + 1], G[i, :i + 1] = G[i, :i + 1].copy(), G[jast, :i + 1].copy()
        else:
            jast = 0

        G[i, i] = np.sqrt(diag[jast])
        nextcol = a[pvec[i + 1:], pvec[i]]
        G[i + 1:, i] = (nextcol - G[i + 1:, :i] @ G[i, :i].T) / G[i, i]
        diag[i + 1:] = 1 - np.sum((G[i + 1:, :i + 1]) ** 2, axis=1)

        i += 1
    return G[pvec.argsort(), :i]


def subspace(a, b, deg=True):
    """
    Angle between two subspaces

    Find the angle between two subspaces specified by the columns of a and b
    Ported from MATLAB subspace

    Args:
        a: subspace
        b: subspace
        deg: return in degree or radian
    Returns:
        angle in radian
    """
    oa = linalg.orth(a)
    ob = linalg.orth(b)
    if oa.shape[1] < ob.shape[1]:
        oa, ob = ob.copy(), oa.copy()
    ob -= oa @ (oa.T @ ob)
    rad = np.arcsin(min(1, linalg.norm(ob, ord=2)))
    return np.degrees(rad) if deg else rad


def orth(x, a):
    """
    Orthogonalize the rows of the loading matrix and apply the corresponding linear transform to the latent variables.

    Args:
        x: latent variables
        a: loading matrix
        normalize_a: use loading or latent to orthogonalize

    Returns:

    """
    U, s, Vh = svd(a, full_matrices=False)  # scipy version
    a_orth = Vh
    x_orth = x @ a @ Vh.T
    return x_orth, a_orth


@jit
def ichol_gauss2(n, omega):
    """
    Incomplete Cholesky factorization of squared exponential covariance

    K \approx GG'

    Args:
        n: size of covariance matrix
        omega: inverse of 2 * squared lengthscale
        r: rank of factorization
        atol: tolerance of convergence

    Returns:
        incomplete lower trianglar matrix (n, r)
    """

    x = np.arange(n)
    diag = np.ones(n, dtype=float)
    pvec = np.arange(n, dtype=int)
    i = 0
    chol = np.zeros((n, n), dtype=float)
    while np.sum(diag[i:]) > 0.0:
        if i > 0:
            jast = diag[i:].argmax()
            jast += i
            # Be caseful! numpy indexing returns a view instead of a copy.
            pvec[i], pvec[jast] = pvec[jast].copy(), pvec[i].copy()
            chol[jast, :i + 1], chol[i, :i + 1] = chol[i, :i + 1].copy(), chol[jast, :i + 1].copy()
        else:
            jast = 0

        chol[i, i] = np.sqrt(diag[jast])
        next_col = np.exp(- omega * (x[pvec[i + 1:]] - x[pvec[i]]) ** 2)
        chol[i + 1:, i] = (next_col - chol[i + 1:, :i] @ chol[i, :i].T) / chol[i, i]
        diag[i + 1:] = 1 - np.sum((chol[i + 1:, :i + 1]) ** 2, axis=1)

        i += 1
    return chol[pvec.argsort(), :i]