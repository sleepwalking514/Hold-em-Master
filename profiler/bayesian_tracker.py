from __future__ import annotations

import math


class BayesianStat:
    def __init__(self, prior_alpha: float = 2.0, prior_beta: float = 3.0):
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        self.alpha = prior_alpha
        self.beta = prior_beta

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1
        else:
            self.beta += 1

    @property
    def mean(self) -> float:
        total = self.alpha + self.beta
        if total == 0:
            return 0.5
        return self.alpha / total

    @property
    def observations(self) -> int:
        return int((self.alpha - self.prior_alpha) + (self.beta - self.prior_beta))

    @property
    def confidence(self) -> float:
        n = self.observations
        if n <= 0:
            return 0.0
        return 1 - 1 / (1 + math.sqrt(n))

    def to_dict(self) -> dict:
        return {
            "prior_alpha": self.prior_alpha,
            "prior_beta": self.prior_beta,
            "alpha": self.alpha,
            "beta": self.beta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BayesianStat:
        stat = cls(d["prior_alpha"], d["prior_beta"])
        stat.alpha = d["alpha"]
        stat.beta = d["beta"]
        return stat
