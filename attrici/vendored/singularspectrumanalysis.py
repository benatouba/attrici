"""Code for Singular Spectrum Analysis."""

# Copyright (c) 2018, Johann Faouzi and pyts contributors
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of pyts nor the names of its contributors may be used to
#   endorse or promote products derived from this software without specific
#   prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Author: Johann Faouzi <johann.faouzi@gmail.com>
# License: BSD-3-Clause

from math import ceil

import numpy as np
from numpy.lib.stride_tricks import as_strided


def _outer_dot(v, X, n_samples, window_size, n_windows):
    X_new = np.empty((n_samples, window_size, window_size, n_windows))
    for i in range(n_samples):
        for j in range(window_size):
            X_new[i, j] = np.dot(np.outer(v[i, :, j], v[i, :, j]), X[i])
    return X_new


def _diagonal_averaging(
    X, n_samples, n_timestamps, window_size, n_windows, grouping_size, gap
):
    X_new = np.empty((n_samples, grouping_size, n_timestamps))
    first_row = [(0, col) for col in range(n_windows)]
    last_col = [(row, n_windows - 1) for row in range(1, window_size)]
    indices = first_row + last_col
    for i in range(n_samples):
        for group in range(grouping_size):
            for j, k in indices:
                X_new[i, group, j + k] = np.diag(
                    X[i, group, :, ::-1], gap - j - k - 1
                ).mean()
    return X_new


def _windowed_view(X, n_samples, n_timestamps, window_size, window_step):
    overlap = window_size - window_step
    shape_new = (n_samples, (n_timestamps - overlap) // window_step, window_size // 1)
    s0, s1 = X.strides
    strides_new = (s0, window_step * s1, s1)
    return as_strided(X, shape=shape_new, strides=strides_new)


class SingularSpectrumAnalysis:
    """Singular Spectrum Analysis.

    Parameters
    ----------
    window_size : int or float (default = 4)
        Size of the sliding window (i.e. the size of each word). If float, it
        represents the percentage of the size of each time series and must be
        between 0 and 1. The window size will be computed as
        ``max(2, ceil(window_size * n_timestamps))``.

    groups : None, int, 'auto', or array-like (default = None)
        The way the elementary matrices are grouped. If None, no grouping is
        performed. If an integer, it represents the number of groups and the
        bounds of the groups are computed as
        ``np.linspace(0, window_size, groups + 1).astype('int64')``.
        If 'auto', then three groups are determined, containing trend,
        seasonal, and residual. If array-like, each element must be array-like
        and contain the indices for each group.

    lower_frequency_bound : float (default = 0.075)
        The boundary of the periodogram to characterize trend, seasonal and
        residual components. It must be between 0 and 0.5.
        Ignored if 'groups' is not set to 'auto'.

    lower_frequency_contribution : float (default = 0.85)
        The relative threshold to characterize trend, seasonal and
        residual components by considering the periodogram.
        It must be between 0 and 1. Ignored if 'groups' is not set to 'auto'.

    References
    ----------
    .. [1] N. Golyandina, and A. Zhigljavsky, "Singular Spectrum Analysis for
           Time Series". Springer-Verlag Berlin Heidelberg (2013).

    .. [2] T. Alexandrov, "A Method of Trend Extraction Using Singular
           Spectrum Analysis", REVSTAT (2008).

    Examples
    --------
    >>> from pyts.datasets import load_gunpoint
    >>> from pyts.decomposition import SingularSpectrumAnalysis
    >>> X, _, _, _ = load_gunpoint(return_X_y=True)
    >>> transformer = SingularSpectrumAnalysis(window_size=5)
    >>> X_new = transformer.transform(X)
    >>> X_new.shape
    (50, 5, 150)

    """

    def __init__(
        self,
        window_size=4,
        groups=None,
        lower_frequency_bound=0.075,
        lower_frequency_contribution=0.85,
    ):
        self.window_size = window_size
        self.groups = groups
        self.lower_frequency_bound = lower_frequency_bound
        self.lower_frequency_contribution = lower_frequency_contribution

    def transform(self, X):
        """Transform the provided data.

        Parameters
        ----------
        X : array-like, shape = (n_samples, n_timestamps)

        Returns
        -------
        X_new : array-like, shape = (n_samples, n_splits, n_timestamps)
            Transformed data. ``n_splits`` value depends on the value of
            ``groups``. If ``groups=None``, ``n_splits`` is equal to
            ``window_size``. If ``groups`` is an integer, ``n_splits`` is
            equal to ``groups``. If ``groups='auto'``, ``n_splits`` is equal
            to three. If ``groups`` is array-like, ``n_splits`` is equal to
            the length of ``groups``. If ``n_splits=1``, ``X_new`` is squeezed
            and its shape is (n_samples, n_timestamps).

        """
        n_samples, n_timestamps = X.shape
        window_size = self._check_params(n_timestamps)
        n_windows = n_timestamps - window_size + 1

        X_window = np.transpose(
            _windowed_view(X, n_samples, n_timestamps, window_size, window_step=1),
            axes=(0, 2, 1),
        ).copy()
        X_tranpose = np.matmul(X_window, np.transpose(X_window, axes=(0, 2, 1)))
        w, v = np.linalg.eigh(X_tranpose)
        w, v = w[:, ::-1], v[:, :, ::-1]

        X_elem = _outer_dot(v, X_window, n_samples, window_size, n_windows)
        X_groups, grouping_size = self._grouping(
            X_elem, n_samples, window_size, n_windows, v
        )
        if window_size >= n_windows:
            X_groups = np.transpose(X_groups, axes=(0, 1, 3, 2))
            gap = window_size
        else:
            gap = n_windows

        X_ssa = _diagonal_averaging(
            X_groups,
            n_samples,
            n_timestamps,
            window_size,
            n_windows,
            grouping_size,
            gap,
        )
        return np.squeeze(X_ssa)

    def _grouping(self, X, n_samples, window_size, n_windows, v):
        if self.groups is None:
            grouping_size = window_size
            X_new = X
        elif self.groups == "auto":
            grouping_size = 3
            f = np.arange(0, 1 + window_size // 2) / window_size
            Pxx = np.abs(np.fft.rfft(v, axis=1, norm="ortho")) ** 2
            if Pxx.shape[-1] % 2 == 0:
                Pxx[:, 1:-1, :] *= 2
            else:
                Pxx[:, 1:, :] *= 2

            Pxx_cumsum = np.cumsum(Pxx, axis=1)
            idx_trend = np.where(f < self.lower_frequency_bound)[0][-1]
            idx_resid = Pxx_cumsum.shape[1] // 2

            c = self.lower_frequency_contribution
            trend = Pxx_cumsum[:, idx_trend, :] / Pxx_cumsum[:, -1, :] > c
            resid = Pxx_cumsum[:, idx_resid, :] / Pxx_cumsum[:, -1, :] < c
            season = np.logical_and(~trend, ~resid)

            X_new = np.zeros((n_samples, grouping_size, window_size, n_windows))
            for i in range(n_samples):
                for j, arr in enumerate((trend, season, resid)):
                    X_new[i, j] = X[i, arr[i]].sum(axis=0)
        elif isinstance(self.groups, int):
            grouping = np.linspace(0, window_size, self.groups + 1).astype("int64")
            grouping_size = len(grouping) - 1
            X_new = np.zeros((n_samples, grouping_size, window_size, n_windows))
            for i, (j, k) in enumerate(zip(grouping[:-1], grouping[1:])):
                X_new[:, i] = X[:, j:k].sum(axis=1)
        else:
            grouping_size = len(self.groups)
            X_new = np.zeros((n_samples, grouping_size, window_size, n_windows))
            for i, group in enumerate(self.groups):
                X_new[:, i] = X[:, group].sum(axis=1)
        return X_new, grouping_size

    def _check_params(self, n_timestamps):
        if not isinstance(self.window_size, (int, np.integer, float, np.floating)):
            raise TypeError("'window_size' must be an integer or a float.")
        if isinstance(self.window_size, (int, np.integer)):
            MIN_WINDOW_SIZE = 2
            if not MIN_WINDOW_SIZE <= self.window_size <= n_timestamps:
                raise ValueError(
                    "If 'window_size' is an integer, it must be greater "
                    "than or equal to {} and lower than or equal to "
                    "n_timestamps (got {}).".format(MIN_WINDOW_SIZE, self.window_size)
                )
            window_size = self.window_size
        else:
            if not 0 < self.window_size <= 1:
                raise ValueError(
                    "If 'window_size' is a float, it must be greater "
                    "than 0 and lower than or equal to 1 "
                    "(got {0}).".format(self.window_size)
                )
            window_size = max(2, ceil(self.window_size * n_timestamps))
        if not (
            self.groups is None
            or (isinstance(self.groups, str) and self.groups == "auto")
            or isinstance(self.groups, (int, list, tuple, np.ndarray))
        ):
            raise TypeError(
                "'groups' must be either None, an integer, " "'auto' or array-like."
            )
        FREQUENCY_BOUND = 0.5
        if not isinstance(self.lower_frequency_bound, (float, np.floating)):
            raise TypeError("'lower_frequency_bound' must be a float.")
        elif not 0 < self.lower_frequency_bound < FREQUENCY_BOUND:
            raise ValueError(
                "'lower_frequency_bound' must be greater than 0 and "
                "lower than {0}.".format(FREQUENCY_BOUND)
            )
        if not isinstance(self.lower_frequency_contribution, (float, np.floating)):
            raise TypeError("'lower_frequency_contribution' must be a float.")
        elif not 0 < self.lower_frequency_contribution < 1:
            raise ValueError(
                "'lower_frequency_contribution' must be greater than 0 "
                "and lower than 1."
            )
        if isinstance(self.groups, (int, np.integer)):
            if not 1 <= self.groups <= self.window_size:
                raise ValueError(
                    "If 'groups' is an integer, it must be greater than or "
                    "equal to 1 and lower than or equal to 'window_size'."
                )
        if isinstance(self.groups, (list, tuple, np.ndarray)):
            idx = np.concatenate(self.groups)
            diff = np.setdiff1d(idx, np.arange(self.window_size))
            flat_list = [item for group in self.groups for item in group]
            if (diff.size > 0) or not (
                all(isinstance(x, (int, np.integer)) for x in flat_list)
            ):
                raise ValueError(
                    "If 'groups' is array-like, all the values in 'groups' "
                    "must be integers between 0 and ('window_size' - 1)."
                )
        return window_size