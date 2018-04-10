def make_toy_data():
    import numpy as np
    ydim = 5
    xdim = 0
    zdim = 2

    length = 100
    ntrial = 20

    a = np.random.randn(zdim, ydim)
    b = -2

    trials = []
    for i in range(ntrial):
        z = np.column_stack((np.sin(np.linspace(0, 8 * np.pi, length)),
                             np.cos(np.linspace(0, 8 * np.pi, length))))
        y = np.random.poisson(np.exp(z @ a + b))
        trials.append({'y': y, 'id': i})

    return trials


def test_varlen():
    from vlgp.core import vem, cut_trials
    from vlgp.preprocess import check_data
    from vlgp.util import get_default_config

    data = make_toy_data()
    config = get_default_config()
    trials, params = check_data(data, config)
    trials = cut_trials(trials, params, config)
    vem(trials, params, config)
