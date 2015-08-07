from __future__ import division

import itertools
import warnings
import time

import numpy as np


def lowerbound(y, Y, mu, omega, m, V, b, a):
    """
    Calculate the lower bound without constant terms
    :param y: (T, N), spike trains
    :param Y: (T, 1 + p*N), vectorized spike history
    :param rate: (T, N), E(E(y|x))
    :param mu: (T, L), prior mean
    :param omega: (L, T, T), prior inverse covariances
    :param m: (T, L), latent posterior mean
    :param V: (L, T, T), latent posterior covariances
    :param b: (1 + p*N, N), coefficients of y
    :param a: (L, N), coefficients of x
    :return lbound: lower bound
    """

    _, L = mu.shape
    T, N = y.shape

    rate = np.empty_like(y)
    for t, n in itertools.product(range(T), range(N)):
        rate[t, n] = saferate(t, n, Y, m, V, b, a)

    lbound = np.sum(y * (np.dot(Y, b) + np.dot(m, a)) - rate)

    for l in range(L):
        lbound += -0.5 * np.dot(m[:, l] - mu[:, l], np.dot(omega[l, :, :], m[:, l] - mu[:, l])) + \
                  -0.5 * np.trace(np.dot(omega[l, :, :], V[l, :, :])) + 0.5 * np.linalg.slogdet(V[l, :, :])[1]

    return lbound


def variational(y, mu, sigma, p, omega=None,
                a0=None, b0=None, m0=None, V0=None, K0=None,
                r0=np.finfo(float).eps, maxiter=5, inneriter=5, tol=np.finfo(float).eps,
                verbose=False):
    """
    :param y: (T, N), spike trains
    :param mu: (T, L), prior mean
    :param sigma: (L, T, T), prior covariance
    :param omega: (L, T, T), inverse prior covariance
    :param p: order of autoregression
    :param maxiter: maximum number of iterations
    :param tol: convergence tolerance
    :return
        m: posterior mean
        V: posterior covariance
        b: coefficients of y
        a: coefficients of x
        lbound: lower bound sequence
        it: number of iterations
    """

    def updaterate(t, n):
        # rate = E(E(y|x))
        for t, n in itertools.product(t, n):
            rate[t, n] = saferate(t, n, Y, m, V, b, a)

    start = time.time()  # time when algorithm starts

    # dimensions
    T, N = y.shape
    _, L = mu.shape

    # identity matrix
    id_m = np.identity(T)
    id_a = np.identity(L)
    id_b = np.identity(1 + p*N)

    # calculate inverse of prior covariance if not given
    if omega is None:
        omega = np.empty_like(sigma)
        for l in range(L):
            omega[l, :, :] = np.linalg.inv(sigma[l, :, :])

    # read-only variables, protection from unexpected assignment
    y.setflags(write=0)
    mu.setflags(write=0)
    sigma.setflags(write=0)
    omega.setflags(write=0)

    # initialize args
    # make a copy to avoid changing initial values
    if m0 is None:
        m = mu.copy()
    else:
        m = m0.copy()

    if V0 is None:
        V = sigma.copy()
    else:
        V = V0.copy()

    if K0 is None:
        K = omega.copy()
    else:
        K = np.empty_like(V)
        for l in range(L):
            K[l, :, :] = np.linalg.inv(V[l, :, :])

    if a0 is None:
        a = np.zeros((L, N))
    else:
        a = a0.copy()

    if b0 is None:
        b = np.zeros((1 + p * N, N))
    else:
        b = b0.copy()

    # construct history
    Y = np.zeros((T, 1 + p * N), dtype=float)
    Y[:, 0] = 1
    for t in range(T):
        if t - p >= 0:
            Y[t, 1:] = y[t - p:t, :].flatten()  # vectorized by row
        else:
            Y[t, 1 + (p - t) * N:] = y[:t, :].flatten()
    # Y_ = np.hstack((Y, m))
    # coeffs = np.linalg.lstsq(Y_, y)[0]  # least-squares calculated for each column of y
    # coeffs = np.zeros((1 + p*N + L, N))

    # initialize rate matrix
    # rate = E(E(y|x))
    rate = np.empty_like(y)
    updaterate(range(T), range(N))

    # initialize lower bound
    lbound = np.full(maxiter, np.NINF, dtype=float)
    lb = lbound[0] = lowerbound(y, Y, mu, omega, m, V, b, a)

    # old values
    old_a = np.copy(a)
    old_b = np.copy(b)
    old_m = np.copy(m)
    old_V = np.copy(V)

    it = 1
    convergent = False
    # MIN_DELTA = tol * (a.size + b.size + m.size + V.size)
    while not convergent and it < maxiter:
        # optimize coefficients
        for n in range(N):
            # optimize b[:, n]
            for _ in range(inneriter):
                grad_b = np.zeros(1 + p * N)
                hess_b = np.zeros((1 + p * N, 1 + p * N))
                for t in range(T):
                    grad_b = np.nan_to_num(grad_b + (y[t, n] - rate[t, n]) * Y[t, :])
                    hess_b = np.nan_to_num(hess_b - rate[t, n] * np.outer(Y[t, :], Y[t, :]))
                # if np.linalg.norm(grad_b) < tol * grad_b.size:
                #     break
                # try:
                #     b[:, n] = b[:, n] - np.linalg.solve(hess_b, grad_b) / grad_b.size * stepsize
                # except np.linalg.LinAlgError:
                #     b[:, n] = b[:, n] + grad_b / grad_b.size
                # b[:, n] = b[:, n] - np.linalg.solve(hess_b + r * np.identity(grad_b.size) * hess_b.trace() / grad_b.size, grad_b)
                r = r0
                pd = False
                while not pd:
                    hess_ = hess_b - r * id_b
                    try:
                        np.linalg.cholesky(-hess_)
                        pd = True
                    except np.linalg.LinAlgError:
                        pd = False
                        r *= 10.0
                        hess_ = hess_b - r * id_b
                b[:, n] = b[:, n] - np.linalg.solve(hess_, grad_b)
                updaterate(range(T), [n])

            # roll back if lower bound decreased
            # lb = lowerbound(y, Y, mu, omega, m, V, b, a)
            # if np.isnan(lb) or lb < lbound[it - 1]:
            #     b[:, n] = old_b[:, n]
            #     updaterate(range(T), [n])

                # optimize a
            for _ in range(inneriter):
                grad_a = np.zeros(L)
                hess_a = np.zeros((L, L))
                for t in range(T):
                    Vt = np.diag(V[:, t, t])
                    w = m[t, :] + np.dot(Vt, a[:, n])
                    grad_a = grad_a + y[t, n] * m[t, :] - rate[t, n] * w
                    hess_a = hess_a - rate[t, n] * (np.outer(w, w) + Vt)
                # if np.linalg.norm(grad_a) < tol * grad_a.size:
                #     break
                # try:
                #     a[:, n] = a[:, n] - np.linalg.solve(hess_a, grad_a) / grad_a.size * stepsize
                # except np.linalg.LinAlgError:
                #     a[:, n] = a[:, n] + grad_a / grad_a.size
                # a[:, n] = a[:, n] - np.linalg.solve(hess_a + r * np.identity(grad_a.size) * hess_a.trace() / grad_a.size, grad_a)
                r = r0
                pd = False
                while not pd:
                    hess_ = hess_a - r * id_a
                    try:
                        np.linalg.cholesky(-hess_)
                        pd = True
                    except np.linalg.LinAlgError:
                        pd = False
                        r *= 10.0
                        hess_ = hess_a - r * id_a
                a[:, n] = a[:, n] - np.linalg.solve(hess_, grad_a)
                a[:, n] = a[:, n] / np.linalg.norm(a)
                updaterate(range(T), [n])

            # roll back
            lb = lowerbound(y, Y, mu, omega, m, V, b, a)
            if np.isnan(lb) or lb < lbound[it - 1]:
                a[:, n] = old_a[:, n]
                updaterate(range(T), [n])

        # optimize posterior
        for l in range(L):
            # optimize V[l]
            for t in range(T):
                k_ = K[l, t, t] - 1 / V[l, t, t]  # \tilde{k}_tt
                old_vtt = V[l, t, t]
                # fixed point iterations
                for _ in range(inneriter):
                    V[l, t, t] = 1 / (omega[l, t, t] - k_ + np.dot(rate[t, :], a[l, :] * a[l, :]))
                    updaterate([t], range(N))
                # update V
                not_t = np.arange(T) != t
                V[np.ix_([l], not_t, not_t)] = V[np.ix_([l], not_t, not_t)] \
                                               + (V[l, t, t] - old_vtt) \
                                                 * np.outer(V[l, t, not_t], V[l, t, not_t]) / (old_vtt * old_vtt)
                V[l, t, not_t] = V[l, not_t, t] = V[l, t, t] * V[l, t, not_t] / old_vtt
                # update k_tt
                K[l, t, t] = k_ + 1 / V[l, t, t]
            updaterate(range(T), range(N))
            # roll back
            lb = lowerbound(y, Y, mu, omega, m, V, b, a)
            if np.isnan(lb) or lb < lbound[it - 1]:
                V[l, :, :] = old_V[l, :, :]
                updaterate(range(T), range(N))

            # optimize m[l]
            for _ in range(inneriter):
                grad_m = np.nan_to_num(np.dot(y - rate, a[l, :]) - np.dot(omega[l, :, :], (m[:, l] - mu[:, l])))
                # if np.linalg.norm(grad_m) < tol * grad_m.size:
                #     break
                hess_m = np.nan_to_num(-np.diag(np.dot(rate, a[l, :] * a[l, :]))) - omega[l, :, :]
                # try:
                #     m[:, l] = m[:, l] - np.linalg.solve(hess_m, grad_m) / grad_m.size * stepsize
                # except np.linalg.LinAlgError:
                #     m[:, l] = m[:, l] + grad_m / grad_m.size
                # m[:, l] = m[:, l] - np.linalg.solve(hess_m + r * np.identity(grad_m.size) * hess_m.trace() / grad_m.size, grad_m)
                r = r0
                pd = False
                while not pd:
                    hess_ = hess_m - r * id_m
                    try:
                        np.linalg.cholesky(-hess_)
                        pd = True
                    except np.linalg.LinAlgError:
                        pd = False
                        r *= 10.0
                        hess_ = hess_m - r * id_m
                m[:, l] = m[:, l] - np.linalg.solve(hess_, grad_m)
                updaterate(range(T), range(N))
            # roll back if lower bound decreased
            lb = lowerbound(y, Y, mu, omega, m, V, b, a)
            if np.isnan(lb) or lb < lbound[it - 1]:
                m[:, l] = old_m[:, l]
                updaterate(range(T), range(N))

        # update lower bound
        lbound[it] = lowerbound(y, Y, mu, omega, m, V, b, a)

        # check convergence
        delta = np.linalg.norm(old_a - a) + np.linalg.norm(old_b - b) \
                + np.linalg.norm(old_m - m) + np.linalg.norm(old_V - V)

        if delta < tol:
            convergent = True

        if verbose:
            print 'Iteration[%d]:' % (it + 1), 'L = %.5f' % lbound[it], 'delta = %.5f' % delta

        old_a[:] = a
        old_b[:] = b
        old_m[:] = m
        old_V[:] = V

        it += 1

    if it == maxiter:
        warnings.warn('not convergent', RuntimeWarning)

    stop = time.time()

    return m, V, b, a, lbound, it, stop - start


def saferate(t, n, Y, m, V, b, a):
    lograte = np.dot(Y[t, :], b[:, n]) + np.dot(m[t, :], a[:, n]) + 0.5 * np.sum(a[:, n] * a[:, n] * V[:, t, t])
    return np.nan_to_num(np.exp(lograte))
