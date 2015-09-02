import itertools
import timeit

import numpy as np
from scipy import linalg


# from numpy import linalg
from util import makeregressor, inchol, sqexpcov


def likelihood(spike, latent, alpha, beta, intercept=True):
    T, N = spike.shape
    L, _ = latent.shape
    k, _ = beta.shape
    p = (k - intercept) // N

    regressor = makeregressor(spike, p, intercept)

    lograte = np.dot(regressor, beta) + np.dot(latent, alpha)
    return np.sum(spike * lograte - np.exp(lograte))


def saferate(t, n, regressor, post_mean, post_cov, beta, alpha):
    lograte = np.dot(regressor[t, :], beta[:, n]) + np.dot(post_mean[t, :], alpha[:, n]) \
              + 0.5 * np.sum(alpha[:, n] ** 2 * post_cov[:, t, t])
    rate = np.nan_to_num(np.exp(lograte))
    return rate if rate > 0 else np.finfo(np.float).eps


def lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov, regressor=None, rate=None):
    """
    Calculate the lower bound
    :param spike: (T, N), spike trains
    :param beta: (1 + p*N, N), coefficients of spike
    :param alpha: (L, N), coefficients of x
    :param prior_mean: (T, L), prior mean
    :param prior_inv: (L, T, T), prior inverse covariances
    :param post_mean: (T, L), latent posterior mean
    :param post_cov: (L, T, T), latent posterior covariances
    :param complete: compute constant terms
    :param regressor: (T, 1 + p*N), vectorized spike makeregressor
    :param rate: (T, N), E(E(spike|x))
    :return lbound: lower bound
    """

    _, L = prior_mean.shape
    # T, N = spike.shape

    lbound = np.sum(spike * (np.dot(regressor, beta) + np.dot(post_mean, alpha)) - rate)

    for l in range(L):
        lbound += -0.5 * np.dot(post_mean[:, l] - prior_mean[:, l],
                                np.dot(prior_inv[l, :, :], post_mean[:, l] - prior_mean[:, l])) \
                  - 0.5 * np.trace(np.dot(prior_inv[l, :, :], post_cov[l, :, :])) \
                  + 0.5 * np.linalg.slogdet(post_cov[l, :, :])[1]
        # lbound += -0.5 * np.dot(post_mean[:, l] - prior_mean[:, l],
        #                         linalg.lstsq(prior_cov[l, :, :], post_mean[:, l] - prior_mean[:, l])[0]) \
        #           - 0.5 * np.trace(linalg.lstsq(prior_cov[l, :, :], post_cov[l, :, :])[0]) \
        #           + 0.5 * np.linalg.slogdet(post_cov[l, :, :])[1]

    return lbound


default_control = {'maxiter': 200,
                   'fixed-point iteration': 3,
                   'tol': 1e-4,
                   'verbose': False}


def variational(spike, p, prior_mean, prior_var, prior_w,
                a0=None, b0=None, m0=None,
                fixalpha=False, fixbeta=False, fixpostmean=False, fixpostcov=False, normofalpha=1.0, intercept=True,
                hyper=False, inchol_tol=1e-7,
                control=default_control):
    """
    :param spike: (T, N), spike trains
    :param p: order of regression
    :param prior_mean: (T, L), prior mean
    :param prior_var: (L,), prior variance
    :param prior_w: (L,), prior inverse of squared lengthscale
    :param a0: (L, N), initial value of alpha
    :param b0: (N, intercept + p * N), initial value of beta
    :param m0: (T, L), initial value of posterior mean
    :param V0: (L, T, T), initial value of posterior covariance
    :param K0: (L, T, T), initial value of posterior covariance inverse
    :param fixalpha: bool, switch of not optimize alpha
    :param fixbeta: bool, switch of not optimize beta
    :param fixpostmean: bool, switch of not optimize posterior mean
    :param fixpostcov: bool, switch of not optimize posterior covariance
    :param normofalpha: norm constraint of alpha
    :param intercept: bool, include intercept term or not
    :param hyper: optimize hyperparameters or not
    :param control: control params
    :return:
        post_mean: posterior mean
        post_cov: posterior covariance
        beta: coefficient of regressor
        alpha: coefficient of latent
        a0: initial value of alpha
        b0: initial value of beta
        lbound: array of lower bounds
        elapsed:
        converged:
    """

    start = timeit.default_timer()  # time when algorithm starts

    def updaterate(rows, cols):
        # rate = E(E(spike|x))
        for row, col in itertools.product(rows, cols):
            rate[row, col] = saferate(row, col, regressor, post_mean, post_cov, beta, alpha)

    # control
    maxiter = control['max iteration']
    fpinter = control['fixed-point iteration']
    tol = control['tol']
    verbose = control['verbose']

    # epsilon
    eps = 2 * np.finfo(np.float).eps

    # dimensions
    T, N = spike.shape
    _, L = prior_mean.shape

    eyeT = np.identity(T)

    # hyperparameters
    variance = prior_var.copy()
    w = prior_w.copy()

    i, j = np.meshgrid(np.arange(T), np.arange(T))
    bmat = -(i - j) ** 2

    prior_chol = np.empty(L, dtype=object)
    prior_cov = np.empty(shape=(L, T, T))
    prior_inv = np.empty(shape=(L, T, T))
    for l in range(L):
        prior_chol[l] = inchol(T, w[l], inchol_tol)
        # prior_cov[l, :, :] = sqexpcov(T, w[l], variance[l]) + eyeT * 1e-7
        # cor = sqexpcov(T, w[l], 1)
        prior_cov[l, :, :] = variance[l] * sqexpcov(T, w[l], 1)
        U, s, Vh = linalg.svd(prior_cov[l, :, :])
        # prior_inv[l, :, :] = np.dot(Vh.T, np.dot(np.diag(np.nan_to_num(np.abs(1/s))), U.T)) / variance[l]
        prior_inv[l, :, :] = np.dot(Vh.T, np.dot(np.diag(np.nan_to_num(np.abs(1/s))), U.T))
        # prior_inv[l, :, :] = linalg.pinv2(prior_cov[l, :, :])
        # pinv = linalg.lstsq(prior_chol[l], eyeT)[0]
        # prior_inv[l, :, :] = np.dot(pinv.T, pinv) / variance[l]
        # prior_inv[l, :, :] = linalg.inv(prior_cov[l, :, :])

    # read-only variables, protection from unexpected assignment
    spike.setflags(write=0)
    prior_mean.setflags(write=0)

    # construct makeregressor
    regressor = makeregressor(spike, p, intercept)
    regressor.setflags(write=0)

    # initialize args
    # make alpha copy to avoid changing initial values
    if m0 is None:
        post_mean = prior_mean.copy()
    else:
        post_mean = m0.copy()

    post_cov = prior_cov.copy()
    post_inv = prior_inv.copy()

    if a0 is None:
        a0 = np.random.randn(L, N)
        a0 /= linalg.norm(a0) / normofalpha
    alpha = a0.copy()

    if b0 is None:
        b0 = linalg.lstsq(regressor, spike)[0]
    beta = b0.copy()

    # initialize rate matrix, rate = E(E(spike|x))
    rate = np.empty_like(spike)
    updaterate(range(T), range(N))

    # initialize lower bound
    lbound = np.full(maxiter, np.NINF)
    lbound[0] = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                           regressor=regressor, rate=rate)

    # valid values of parameters from previous iteration
    good_alpha = alpha.copy()
    good_beta = beta.copy()
    good_post_mean = post_mean.copy()
    good_post_cov = post_cov.copy()

    # temporary storage for recovery
    last_b = np.empty_like(beta)
    last_a = np.empty_like(alpha)
    last_m = np.empty_like(post_mean)
    last_rate = np.empty_like(rate)
    last_V = np.empty_like(post_cov)
    last_prior_cov = np.empty_like(prior_cov)
    last_prior_inv = np.empty_like(prior_inv)

    stepsize_alpha = np.ones(N)
    stepsize_beta = np.ones(N)
    stepsize_post_mean = np.ones(L)
    stepsize_w = np.ones(L)
    deflation = 0.5
    inflation = 1.5
    thld = 0.75

    # Optimization
    it = 1
    converged = False
    while not converged and it < maxiter:
        if not fixbeta:
            for n in range(N):
                grad_b = np.dot(regressor.T, spike[:, n] - rate[:, n])
                neg_hess_b = np.dot(regressor.T, (regressor.T * rate[:, n]).T)
                if linalg.norm(grad_b, ord=np.inf) < eps:
                    break
                try:
                    delta_b = stepsize_beta[n] * linalg.solve(neg_hess_b, grad_b)
                except linalg.LinAlgError as e:
                    print('beta', e)
                    continue
                last_b[:, n] = beta[:, n]
                last_rate[:, n] = rate[:, n]
                predict = np.inner(grad_b, delta_b) - 0.5 * np.dot(delta_b, np.dot(neg_hess_b, delta_b))
                beta[:, n] += delta_b
                updaterate(range(T), [n])
                lb = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                                regressor=regressor, rate=rate)
                if np.isnan(lb) or lb < lbound[it - 1]:
                    # Decrease the stepsize if the lower bound decreases.
                    # Add a small positive number to prevent becoming 0.
                    stepsize_beta[n] *= deflation
                    stepsize_beta[n] += eps
                    # Recover last valid values
                    beta[:, n] = last_b[:, n]
                    rate[:, n] = last_rate[:, n]
                elif lb - lbound[it - 1] > thld * predict:
                    # Increase the stepsize if the real increment is more than expected.
                    stepsize_beta[n] *= inflation
                    # if stepsize_beta[n] > 1:
                    #     stepsize_beta[n] = 1.0

        if not fixalpha:
            for l in range(L):
                grad_a = np.dot((spike - rate).T, post_mean[:, l]) \
                         - np.dot(rate.T, post_cov[l, :, :].diagonal()) * alpha[l, :]
                neg_hess_a = np.diag(np.dot(rate.T, post_mean[:, l] ** 2)
                                     + 2 * np.dot(rate.T, post_mean[:, l] * post_cov[l, :, :].diagonal()) * alpha[l, :]
                                     + np.dot(rate.T, post_cov[l, :, :].diagonal() ** 2) * alpha[l, :] ** 2
                                     + np.dot(rate.T, post_cov[l, :, :].diagonal()))
                if linalg.norm(grad_a, ord=np.inf) < eps:
                    break
                try:
                    delta_a = stepsize_alpha[l] * linalg.solve(neg_hess_a, grad_a)
                except linalg.LinAlgError as e:
                    print('alpha', e)
                    continue
                last_a[l, :] = alpha[l, :]
                last_rate[:] = rate[:]
                alpha[l, :] += delta_a
                alpha[l, :] /= linalg.norm(alpha[l, :]) / normofalpha
                delta_a = alpha[l, :] - last_a[l, :]
                predict = np.inner(grad_a, delta_a) - 0.5 * np.dot(delta_a, np.dot(neg_hess_a, delta_a))
                updaterate(range(T), range(N))
                lb = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                                regressor=regressor, rate=rate)
                if np.isnan(lb) or lb - lbound[it - 1] < 0:
                    stepsize_alpha[l] *= deflation
                    stepsize_alpha[l] += eps
                    alpha[l, :] = last_a[l, :]
                    rate[:] = last_rate[:]
                elif lb - lbound[it - 1] > thld * predict:
                    stepsize_alpha[l] *= inflation
                    # if stepsize_alpha[l] > 1:
                    #     stepsize_alpha[l] = 1.0

        # posterior mean
        if not fixpostmean:
            for l in range(L):
                # grad_m = np.dot(spike - rate, alpha[l, :]) \
                #          - linalg.solve(prior_cov[l, :, :], post_mean[:, l] - prior_mean[:, l])
                grad_m = np.dot(spike - rate, alpha[l, :]) \
                         - np.dot(prior_inv[l, :, :], post_mean[:, l] - prior_mean[:, l])
                w = np.dot(rate, alpha[l, :] ** 2)
                wsqrt = np.mat(np.diag(np.sqrt(w)))
                bmat = eyeT + wsqrt * np.mat(prior_cov[l, :, :]) * wsqrt
                bchol = linalg.cholesky(bmat, lower=True)
                hinv = prior_cov[l, :, :] - \
                       np.mat(prior_cov[l, :, :]) * wsqrt * \
                       np.mat(linalg.lstsq(bchol.T, linalg.lstsq(bchol, wsqrt * np.mat(prior_cov[l, :, :]))[0])[0])

                if linalg.norm(grad_m, ord=np.inf) < eps:
                    break
                try:
                    delta_m = stepsize_post_mean[l] * np.dot(hinv, grad_m)
                except linalg.LinAlgError as e:
                    print('post_mean', e)
                    continue
                last_m[:, l] = post_mean[:, l]
                last_rate[:] = rate
                post_mean[:, l] = post_mean[:, l] + delta_m
                post_mean[:, l] -= np.mean(post_mean[:, l])
                delta_m = post_mean[:, l] - last_m[:, l]
                predict = np.inner(grad_m, delta_m) - 0.5 * np.dot(delta_m, linalg.lstsq(hinv, delta_m)[0])
                updaterate(range(T), range(N))
                lb = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                                regressor=regressor, rate=rate)
                if np.isnan(lb) or lb < lbound[it - 1]:
                    stepsize_post_mean[l] *= deflation
                    stepsize_post_mean[l] += eps
                    post_mean[:, l] = last_m[:, l]
                    rate[:] = last_rate
                elif lb - lbound[it - 1] > thld * predict:
                    stepsize_post_mean[l] *= inflation
                    # if stepsize_post_mean[l] > 1:
                    #     stepsize_post_mean[l] = 1.0

        # posterior covariance
        if not fixpostcov:
            for l in range(L):
                w = np.dot(rate, alpha[l, :] ** 2)
                wsqrt = np.mat(np.diag(np.sqrt(w)))
                bmat = eyeT + wsqrt * np.mat(prior_cov[l, :, :]) * wsqrt
                bchol = linalg.cholesky(bmat, lower=True)
                post_cov[l, :, :] = prior_cov[l, :, :] - \
                                    np.mat(prior_cov[l, :, :]) * wsqrt * \
                                    np.mat(linalg.lstsq(bchol.T,
                                                        linalg.lstsq(bchol, wsqrt * np.mat(prior_cov[l, :, :]))[0])[0])
                updaterate(range(T), range(N))

        if hyper and it % 5 == 0:
            last_prior_cov[:] = prior_cov
            last_prior_inv[:] = prior_inv
            for l in range(L):
                new_var = variance[l] * (np.dot(post_mean[:, l] - prior_mean[:, l],
                                                np.dot(prior_inv[l, :, :], post_mean[:, l] - prior_mean[:, l]))
                                         + np.trace(np.dot(prior_inv[l, :, :], post_cov[l, :, :]))) / T
                # prior_cov[l, :, :] *= new_var / variance[l]
                # prior_inv[l, :, :] *= variance[l] / new_var
                # lb = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                #                 regressor=regressor, rate=rate)
                # if np.isnan(lb) or lb < lbound[it - 1]:
                #     print('new variance failed')
                #     prior_cov[l, :, :] = last_prior_cov
                #     prior_inv[l, :, :] = last_prior_inv
                # else:
                variance[l] = new_var
                d = post_mean[:, l] - prior_mean[:, l]
                amat = np.mat(prior_inv[l, :, :]) * np.mat(prior_cov[l, :, :] * bmat) * np.mat(prior_inv[l, :, :])
                grad_w = (np.inner(d, np.dot(amat, d)) + np.trace(np.dot(amat, post_cov[l, :, :])) -
                          np.trace(np.dot(prior_inv[l, :, :], prior_cov[l, :, :] * bmat))) / 2
                w[l] += stepsize_w[l] * grad_w

                print('Hyper[{}] = {}, {}'.format(l, variance[l], w[l]))

                prior_cov[l, :, :] = sqexpcov(T, w[l], variance[l])
                U, s, Vh = linalg.svd(prior_cov[l, :, :])
                prior_inv[l, :, :] = np.dot(Vh.T, np.dot(np.diag(np.nan_to_num(np.abs(1/s))), U.T))
                lb = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                                regressor=regressor, rate=rate)
                if np.isnan(lb) or lb < lbound[it - 1]:
                    print('new hyper failed')
                    prior_cov[l, :, :] = last_prior_cov[l, :, :]
                    prior_inv[l, :, :] = last_prior_inv[l, :, :]
                    stepsize_w[l] *= 0.5

        # store lower bound
        lbound[it] = lowerbound(spike, beta, alpha, prior_mean, prior_cov, prior_inv, post_mean, post_cov,
                                regressor=regressor, rate=rate)

        # check convergence
        chg_alpha = 0.0 if fixalpha else np.max(np.abs(good_alpha - alpha))
        chg_beta = 0.0 if fixbeta else np.max(np.abs(good_beta - beta))
        chg_post_mean = 0.0 if fixpostmean else np.max(np.abs(good_post_mean - post_mean))
        chg_post_cov = 0.0 if fixpostcov else np.max(np.abs(good_post_cov - post_cov))
        change = max(chg_alpha, chg_beta, chg_post_mean, chg_post_cov)

        if change < tol:
            converged = True

        if verbose:
            print('\nIteration[{:d}]:\n'
                  'lower bound = {:.5f}\n'
                  'increment = {:.10f}\n'
                  'change in alpha = {:.10f}\n'
                  'change in beta = {:.10f}\n'
                  'change in posterior mean = {:.10f}\n'
                  'change in posterior covariance = {:.10f}'.format(it + 1, lbound[it], lbound[it] - lbound[it - 1],
                                                                    chg_alpha, chg_beta, chg_post_mean, chg_post_cov))

        # store current iteration
        good_alpha[:] = alpha
        good_beta[:] = beta
        good_post_mean[:] = post_mean
        good_post_cov[:] = post_cov

        it += 1

    stop = timeit.default_timer()

    return lbound[:it], post_mean, post_cov, alpha, beta, a0, b0, stop - start, converged
