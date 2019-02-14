"""
Tools for working with linear and linearized models.
"""

import attr
import numpy as np
import scipy as sp
from profiled import profiled

from sklearn.linear_model import LogisticRegressionCV, LogisticRegression
from sklearn.svm import SVC

from trickster.base import WithProblemContext


def _get_forward_grad_lr(clf, x, target_class=None):
    return clf.coef_[0]


def _get_forward_grad_svm_rbf(clf, x, target_class=None):
    kernel_grads = []
    for sv in clf.support_vectors_:
        kernel_grads.append(
            2
            * clf.gamma
            * (x - sv)
            * np.exp(-clf.gamma * np.linalg.norm(x - sv, ord=2)**2)
        )

    return np.dot(clf.dual_coef_[0], np.array(kernel_grads))


def _get_forward_grad_default(clf, x, target_class=None):
    return clf.grad(x, target_class)


def get_forward_grad(clf, x, target_class=None):
    """Get the forward gradient of a classifier.

    :param clf: Classifier.
    :param x: Input.
    :param target_class: Currently not supported.
    """
    if isinstance(clf, LogisticRegressionCV) or isinstance(clf, LogisticRegression):
        return _get_forward_grad_lr(clf, x, target_class)

    elif isinstance(clf, SVC) and clf.kernel == 'rbf':
        return _get_forward_grad_svm_rbf(clf, x, target_class)

    else:
        return _get_forward_grad_default(clf, x, target_class)


def create_reduced_linear_classifier(clf, x, transformable_feature_idxs):
    r"""Construct a reduced-dimension classifier based on the original one for a given example.

    The reduced-dimension classifier should behave the same way as the original one, but operate in
    a smaller feature space. This is done by fixing the score of the classifier on a static part of
    ``x``, and integrating it into the bias parameter of the reduced classifier.

    For example, let $$x = [1, 2, 3]$$, weights of the classifier $$w = [1, 1, 1]$$ and bias term $$b =
    0$$, and the only transformable feature index is 0. Then the reduced classifier has weights $$w' =
    [1]$$, and the bias term incorporates the non-transformable part of $$x$$: $$b' = -1 \cdot 2 + 1
    \cdot 3$$.

    :param clf: Original logistic regression classifier
    :param x: An example
    :param transformable_feature_idxs: List of features that can be changed in the given example.
    """

    if not isinstance(clf, LogisticRegressionCV) or not isinstance(clf, LogisticRegression):
        raise ValueError("Only logistic regression classifiers can be reduced.")

    # Establish non-transformable feature indexes.
    feature_idxs = np.arange(x.size)
    non_transformable_feature_idxs = np.setdiff1d(
        feature_idxs, transformable_feature_idxs
    )

    # Create the reduced classifier.
    clf_reduced = LogisticRegressionCV()
    clf_reduced.coef_ = clf.coef_[:, transformable_feature_idxs]
    clf_reduced.intercept_ = np.dot(
        clf.coef_[0, non_transformable_feature_idxs], x[non_transformable_feature_idxs]
    )
    clf_reduced.intercept_ += clf.intercept_

    assert np.allclose(
        clf.predict_proba([x]),
        clf_reduced.predict_proba([x[transformable_feature_idxs]]),
    )
    return clf_reduced


def dist_to_decision_boundary(clf, x, target_class, target_confidence, lp_space):
    """
    Compute distance to the decision boundary of a binary linear classifier.
    """
    confidence = clf.predict_proba([x])[0, target_class]
    if confidence >= target_confidence:
        return 0.0

    score = clf.decision_function([x])[0]

    # If target confidence is not 0.5, correct the score.
    if target_confidence != 0.5:
        delta = sp.special.logit(target_confidence)
        delta *= -1 if target_class == 1 else 1
        score += delta

    # Compute the distance to the boundary.
    fgrad = get_forward_grad(clf, x, target_class=target_class)
    result = np.abs(score) / np.linalg.norm(fgrad, ord=lp_space.q)
    return result


class LinearHeuristic(WithProblemContext):
    r"""$$L_p$$ distance to the decision boundary of a binary linear classifier.

    :param problem_ctx: Problem context.
    """

    @profiled
    def __call__(self, x):
        ctx = self.problem_ctx
        if ctx.epsilon == 0.0:
            return 0.0

        h = dist_to_decision_boundary(
            clf=ctx.clf,
            target_class=ctx.target_class,
            target_confidence=ctx.target_confidence,
            lp_space=ctx.lp_space,
            x=x
        )
        return h * ctx.epsilon


@attr.s
class LinearGridHeuristic(LinearHeuristic):
    """Snaps values of a linear heuristic to values on a regular grid.

    This is useful when the transformations in the transformation graph
    have fixed costs.

    :param problem_ctx: Problem context.
    :param grid_step: Regular grid step.
    """

    grid_step = attr.ib()

    @profiled
    def __call__(self, x):
        h = super().__call__(x)
        snapped = np.ceil(h / self.grid_step) * self.grid_step
        return snapped

