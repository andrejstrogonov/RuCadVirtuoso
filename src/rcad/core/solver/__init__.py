"""Newton-Raphson решатель для MNA (rcad.core.solver).

Решает нелинейную систему A(x)*x = b(x) итерационно.
"""

from __future__ import annotations

import numpy as np

from rcad.diagnostics import ConvergenceError


class NewtonSolver:
    def __init__(self, tol: float = 1e-9, max_iter: int = 100) -> None:
        self.tol = tol
        self.max_iter = max_iter
        self.iterations = 0
        self.converged = False

    def solve(self, assemble_func, x0: np.ndarray) -> np.ndarray:
        """Решить A(x)*x = b(x) методом Ньютона.

        assemble_func(x) → (A, b) матрица и правая часть в точке x.
        """
        x = x0.copy()
        self.iterations = 0
        self.converged = False

        for it in range(self.max_iter):
            self.iterations = it + 1
            A, b = assemble_func(x)
            r = b - A @ x
            res_norm = float(np.max(np.abs(r)))
            if res_norm < self.tol:
                self.converged = True
                return x
            try:
                dx = np.linalg.solve(A, r)
            except np.linalg.LinAlgError:
                raise ConvergenceError("матрица системы вырождена")
            x = x + dx

        self.converged = False
        raise ConvergenceError(f"не сошлось за {self.max_iter} итераций")


def solve_linear(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Решить линейную систему A*x = b."""
    return np.linalg.solve(A, b)
