"""Small-signal and modal-interaction analysis without plotting code."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from scipy.linalg import block_diag, eig


class SmallSignalAnalyzer:
    def __init__(self, system: Any) -> None:
        self.system = system
        self.latestAnalysis: dict[str, Any] = {}

    def analyze(self, operatingPoint: dict[str, Any]) -> dict[str, Any]:
        analysis = self.system.rlGrid.analyzeSmallSignal(
            operatingPoint["state"], operatingPoint["reference"],
            2 * np.pi * self.system.base["frequency_Hz"],
        )
        self.latestAnalysis = analysis
        return analysis

    @staticmethod
    def analyzeModes(
        stateMatrix: Any, stateNames: Iterable[str], modeLabels: Iterable[str] | None = None
    ) -> dict[str, Any]:
        A = np.asarray(stateMatrix, dtype=float)
        names = list(map(str, stateNames))
        labels = list(map(str, modeLabels)) if modeLabels is not None else [str(i + 1) for i in range(len(names))]
        eigenvalues, leftVectors, rightVectors = eig(A, left=True, right=True)
        for i in range(len(eigenvalues)):
            pairProduct = np.vdot(leftVectors[:, i], rightVectors[:, i])
            if abs(pairProduct) > 1e-10:
                leftVectors[:, i] /= np.conj(pairProduct)
        participation = np.abs(rightVectors * np.conj(leftVectors))
        participation /= np.maximum(participation.sum(axis=0, keepdims=True), np.finfo(float).eps)
        naturalFrequency = np.abs(eigenvalues)
        dampingRatio = -eigenvalues.real / np.maximum(naturalFrequency, np.finfo(float).eps)
        dominantIndices = participation.argmax(axis=0)
        modeTable = [
            {
                "idx": labels[i], "eig": eigenvalues[i], "wn": naturalFrequency[i],
                "zeta": dampingRatio[i], "dominantStates": names[dominantIndices[i]],
            }
            for i in range(len(eigenvalues))
        ]
        return {
            "eigenvalues": eigenvalues, "rightEigenvectors": rightVectors,
            "leftEigenvectors": leftVectors, "participation": participation,
            "modeTable": modeTable,
        }

    def _partitionModalTransform(self, partition: Any, blockStarts: Any):
        stateCount = len(self.system.stateNames)
        partition = np.asarray(partition, dtype=int).reshape(-1)
        blockStarts = np.asarray(blockStarts, dtype=int).reshape(-1)
        # Accept MATLAB's one-based indices at the public boundary.
        if set(partition.tolist()) == set(range(1, stateCount + 1)):
            partition = partition - 1
        if blockStarts.size and blockStarts[0] == 1:
            blockStarts = blockStarts - 1
        point = self.system.initialize()
        stateMatrix = self.system.rlGrid.getStateMatrix(point["state"], point["reference"])
        partitionedMatrix = stateMatrix[np.ix_(partition, partition)]
        stops = np.r_[blockStarts[1:], stateCount]
        rightBlocks, leftBlocks = [], []
        for start, stop in zip(blockStarts, stops):
            _, right = eig(partitionedMatrix[start:stop, start:stop])
            if np.linalg.matrix_rank(right) != right.shape[0]:
                raise ValueError("subsystem has a singular modal basis")
            rightBlocks.append(right)
            leftBlocks.append(np.linalg.inv(right).conj().T)
        return stateMatrix, partitionedMatrix, block_diag(*rightBlocks), block_diag(*leftBlocks)

    def partitionSubsystem(self, partition: Any, blockStarts: Any, maskedIndices: Any = None):
        stateMatrix, partitionedMatrix, rightBasis, leftBasis = self._partitionModalTransform(partition, blockStarts)
        modalMatrix = leftBasis.conj().T @ partitionedMatrix @ rightBasis
        if maskedIndices:
            rows, columns = (np.asarray(v, dtype=int).reshape(-1) for v in maskedIndices)
            if rows.size and rows.min() >= 1 and columns.size and columns.min() >= 1:
                rows, columns = rows - 1, columns - 1
            modalMatrix[np.ix_(rows, columns)] = 0
        reconstructedMatrix = rightBasis @ modalMatrix @ leftBasis.conj().T
        return modalMatrix, stateMatrix, partitionedMatrix, reconstructedMatrix

    def eigenvalueShift(self, partition: Any, blockStarts: Any, maskedIndices: Any = None):
        modalMatrix, *_ = self.partitionSubsystem(partition, blockStarts, maskedIndices)
        return np.linalg.eigvals(modalMatrix), np.diag(modalMatrix)

    def listEigenvalueShift(self, maskedIndices: Any, partition: Any, blockStarts: Any):
        localMatrix, _, partitionedMatrix, _ = self.partitionSubsystem(partition, blockStarts)
        reducedMatrix, *_ = self.partitionSubsystem(partition, blockStarts, maskedIndices)
        fullEigenvalues, leftVectors, rightVectors = eig(partitionedMatrix, left=True, right=True)
        participation = np.abs(rightVectors * np.conj(leftVectors))
        dominant = participation.argmax(axis=0)
        order = np.asarray(partition, dtype=int).reshape(-1)
        if order.size and order.min() >= 1:
            order -= 1
        names = np.asarray(self.system.stateNames, dtype=object)[order]
        local = self.matchEigenvalues(fullEigenvalues, np.diag(localMatrix))
        reduced = self.matchEigenvalues(fullEigenvalues, np.diag(reducedMatrix))
        return [
            {
                "related_state": str(names[dominant[i]]),
                "local_lambda": f"{local[i].real:.1e}{local[i].imag:+.1e}j",
                "full_lambda": f"{fullEigenvalues[i].real:.1e}{fullEigenvalues[i].imag:+.1e}j",
                "reduced_lambda": f"{reduced[i].real:.1e}{reduced[i].imag:+.1e}j",
                "delta_lambda": f"{(fullEigenvalues[i] - reduced[i]).real:.1e}{(fullEigenvalues[i] - reduced[i]).imag:+.1e}j",
                "local_value": local[i], "full_value": fullEigenvalues[i],
                "reduced_value": reduced[i], "delta_value": fullEigenvalues[i] - reduced[i],
            }
            for i in range(len(fullEigenvalues))
        ]

    @staticmethod
    def estimateShift(modalMatrix: Any, targetIndex: int, interactionIndices: Any) -> complex:
        matrix = np.asarray(modalMatrix, dtype=complex)
        target = targetIndex - 1 if targetIndex >= 1 else targetIndex
        interactions = np.asarray(interactionIndices, dtype=int).reshape(-1)
        if interactions.size and interactions.min() >= 1:
            interactions -= 1
        delta = 0j
        for index in interactions:
            denominator = matrix[target, target] - matrix[index, index]
            if abs(denominator) <= np.finfo(float).eps:
                raise ValueError("cannot estimate a shift between repeated local modes")
            product = matrix[target, index] * matrix[index, target]
            ratio = product / denominator**2
            if abs(1 - ratio) <= np.finfo(float).eps:
                raise ValueError("modal shift correction is singular")
            delta += (-product / denominator) / (1 - ratio)
        return delta

    @staticmethod
    def matchEigenvalues(reference: Any, candidates: Any) -> np.ndarray:
        reference = np.asarray(reference, dtype=complex).reshape(-1)
        candidates = np.asarray(candidates, dtype=complex).reshape(-1)
        available = np.ones(candidates.size, dtype=bool)
        matched = np.empty_like(reference)
        for i, value in enumerate(reference):
            distance = np.where(available, np.abs(candidates - value), np.inf)
            index = int(distance.argmin())
            matched[i] = candidates[index]
            available[index] = False
        return matched
