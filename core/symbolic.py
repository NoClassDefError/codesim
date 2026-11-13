"""Fast symbolic Jacobians through common-subexpression elimination (CSE).

``sp.Matrix.jacobian`` differentiates every entry of the fully expanded model.
Converter models with limiters (``Abs``, ``tanh``) repeat large subexpressions,
so the expanded Jacobian swells (e.g. 1.8k -> 39k operations) and takes tens of
seconds. Here the model is first reduced with CSE into intermediates ``w_k``,
and the chain rule is applied through them (forward mode). This gives the same
Jacobian, typically 50-100x faster and many times smaller, written in terms of
the intermediates.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import sympy as sp

Replacements = list[tuple[sp.Symbol, sp.Expr]]


def cseJacobian(
    expressions: Iterable[sp.Expr] | sp.MatrixBase,
    variables: Sequence[sp.Symbol],
    *,
    prefix: str = "w",
) -> tuple[Replacements, sp.ImmutableMatrix]:
    """Jacobian of ``expressions`` with respect to ``variables`` in CSE form.

    Returns ``(replacements, J)``: ``replacements`` is the ordered list of
    intermediates ``(w_k, expression)``, where each expression may use earlier
    intermediates, and ``J`` is written in terms of ``variables``, parameters and
    the ``w_k``. Substituting the intermediates back in reverse order yields
    ``Matrix(expressions).jacobian(variables)``.

    The intermediates are real symbols. With complex symbols SymPy keeps
    ``d|w|/dw`` as an unevaluated ``Derivative``.
    """
    rows = list(expressions)
    variables = list(variables)
    if not rows:
        return [], sp.ImmutableMatrix(sp.zeros(0, len(variables)))
    replacements, reduced = sp.cse(
        rows, symbols=sp.numbered_symbols(prefix, real=True), optimizations="basic",
    )
    gradients: dict[sp.Symbol, sp.Matrix] = {}

    def gradient(expression: sp.Expr) -> sp.Matrix:
        row = sp.Matrix([[sp.diff(expression, variable) for variable in variables]])
        for intermediate in expression.free_symbols & gradients.keys():
            row += sp.diff(expression, intermediate) * gradients[intermediate]
        return row

    for symbol, expression in replacements:
        gradients[symbol] = gradient(expression)
    jacobian = sp.Matrix.vstack(*[gradient(expression) for expression in reduced]) \
        if variables else sp.zeros(len(reduced), 0)
    if jacobian.has(sp.Derivative):
        raise ValueError("Jacobian contains unresolved symbolic derivatives")
    return pruneReplacements(replacements, jacobian), sp.ImmutableMatrix(jacobian)


def splitColumns(
    replacements: Replacements, jacobian: sp.MatrixBase, columns: int,
) -> tuple[tuple[Replacements, sp.ImmutableMatrix], tuple[Replacements, sp.ImmutableMatrix]]:
    """Split a CSE Jacobian into its first ``columns`` columns and the rest.

    Each part keeps only the intermediates it uses, so one CSE pass serves
    e.g. both ``dF/dx`` and ``dF/du``.
    """
    left = sp.ImmutableMatrix(jacobian[:, :columns])
    right = sp.ImmutableMatrix(jacobian[:, columns:])
    return (
        (pruneReplacements(replacements, left), left),
        (pruneReplacements(replacements, right), right),
    )


def pruneReplacements(replacements: Replacements, expressions: Any) -> Replacements:
    """Keep only the intermediates ``expressions`` needs, directly or transitively."""
    used = sp.Matrix(expressions).free_symbols if not isinstance(expressions, set) else expressions
    needed = {symbol for symbol, _ in replacements if symbol in used}
    for symbol, expression in reversed(replacements):
        if symbol in needed:
            needed.update(expression.free_symbols)
    return [(symbol, expression) for symbol, expression in replacements if symbol in needed]


def expandCse(replacements: Replacements, matrix: sp.MatrixBase) -> sp.ImmutableMatrix:
    """Substitute the intermediates back, giving the fully expanded matrix."""
    expanded = sp.Matrix(matrix)
    for symbol, expression in reversed(replacements):
        expanded = expanded.xreplace({symbol: expression})
    return sp.ImmutableMatrix(expanded)


def lambdifyCse(
    arguments: Sequence[sp.Symbol],
    replacements: Replacements,
    expressions: Any,
):
    """Compile ``expressions`` with precomputed intermediates (NumPy backend)."""
    return sp.lambdify(
        list(arguments), expressions, modules="numpy",
        cse=lambda reduced: (replacements, reduced), docstring_limit=0,
    )
