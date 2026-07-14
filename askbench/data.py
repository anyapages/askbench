"""Minimal single-cell container plus a synthetic Perturb-seq generator with known
ground truth, so the toolkit can be built and validated before a real Perturb-seq
dataset is wired in. The real build swaps this for anndata/scanpy; the toolkit only
touches the small surface defined here, so nothing downstream changes."""
from __future__ import annotations

import numpy as np


class CellData:
    """Cells-by-genes expression with a per-cell perturbation label."""

    def __init__(self, X, genes, perturbations, control="NTC"):
        self.X = np.asarray(X, dtype=float)
        self.genes = list(genes)
        self.perturbations = np.asarray(perturbations)
        self.control = control
        self._gidx = {g: i for i, g in enumerate(self.genes)}

    @property
    def n_cells(self) -> int:
        return self.X.shape[0]

    @property
    def n_genes(self) -> int:
        return self.X.shape[1]

    def has_gene(self, gene) -> bool:
        return gene in self._gidx

    def gene_expr(self, gene):
        return self.X[:, self._gidx[gene]]

    def perturbation_labels(self):
        """Unique perturbations (control excluded), in first-seen order."""
        seen = dict.fromkeys(self.perturbations.tolist())
        return [p for p in seen if p != self.control]

    def mask(self, pert):
        return self.perturbations == pert


def normalize(data: CellData) -> CellData:
    """Total-count normalise to median depth, then log1p. Standard first step so
    per-cell sequencing depth cannot masquerade as a real biological effect."""
    counts = data.X
    depth = counts.sum(axis=1, keepdims=True)
    depth[depth == 0] = 1.0
    target = np.median(depth)
    normed = np.log1p(counts / depth * target)
    return CellData(normed, data.genes, data.perturbations, data.control)


def make_synthetic(seed=0, n_genes=200, n_perturbations=30, cells_per=120,
                   control="NTC"):
    """Synthetic Perturb-seq with planted ground truth: a few perturbations
    genuinely raise or lower a target gene, one carries a real-looking effect on
    far too few cells (a trap for the Skeptic), the rest are null.
    Returns (CellData, truth_dict)."""
    rng = np.random.default_rng(seed)
    genes = [f"GENE{i}" for i in range(n_genes)]
    target = "GENE7"                       # the gene the test question asks about
    tgt_i = genes.index(target)
    base = rng.gamma(2.0, 1.0, size=n_genes) + 0.2

    effects = {"KO_0": 2.2, "KO_1": 1.8, "KO_2": 0.4, "KO_3": 1.9}  # multipliers
    small_n = {"KO_3": 6}                  # KO_3: real effect, underpowered

    perts = [control] + [f"KO_{i}" for i in range(n_perturbations)]
    rows, labels = [], []
    for p in perts:
        n = small_n.get(p, cells_per)
        lam = np.tile(base, (n, 1))
        if p in effects:
            lam[:, tgt_i] *= effects[p]
        rows.append(rng.poisson(lam))
        labels += [p] * n
    return (CellData(np.vstack(rows), genes, np.array(labels), control),
            {"target": target, "effects": effects, "small_n": small_n})
