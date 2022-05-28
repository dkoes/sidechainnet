"""Losses for training."""

import numpy as np
import prody as pr
import torch

from sidechainnet.structure.build_info import NUM_COORDS_PER_RES


def compute_batch_drmsd(true_coordinates, pred_coordinates, seq, verbose=False):
    """Compute batch-averaged DRMSD between two sets of coordinates.

    Args:
        true_coordinates (torch.Tensor): Tensor of true atomic coordinates
            (batch_size * length * NUM_COORDS_PER_RES).
        pred_coordinates (torch.Tensor): Tensor of predicted atomic coordinates
            (batch_size * length * NUM_COORDS_PER_RES).
        seq (torch.Tensor): Tensor of protein sequences represented as integers
            (batch_size * length).
        verbose (bool, optional): If True, print DRMSD/lnDRMSD values as they are
            computed. Defaults to False.

    Returns:
        torch.Tensor: Geometric mean of DRMSD values for each protein in the batch.
            Lower is better.
    """
    drmsds = torch.tensor(0.0)
    raw_drmsds = torch.tensor(0.0)
    for pc, tc, s in zip(pred_coordinates, true_coordinates, seq):
        # Remove batch_padding from true coords
        batch_padding = _tile((s != 20), 0, NUM_COORDS_PER_RES)
        tc = tc[batch_padding]
        missing_atoms = torch.isnan(tc).all(axis=-1)
        tc = tc[~missing_atoms]
        pc = pc[~missing_atoms]

        d = drmsd(tc, pc)
        drmsds += d / (len(tc) // NUM_COORDS_PER_RES)
        raw_drmsds += d

    if verbose:
        print(f"DRMSD = {raw_drmsds.mean():.2f}, lnDRMSD = {drmsds.mean():.2f}")
    return drmsds.mean()


def drmsd(a, b):
    """Return distance root-mean-squared-deviation between tensors a and b.

    Given 2 coordinate tensors, returns the dRMSD between them. Both
    tensors must be the exact same shape. It works by creating a mask of the
    upper-triangular indices of the pairwise distance matrix (excluding the
    diagonal). Then, the resulting values are compared with PyTorch's MSE loss.

    Args:
        a, b (torch.Tensor): coordinate tensor with shape (L x 3).

    Returns:
        res (torch.Tensor): DRMSD between a and b.
    """
    a_ = pairwise_internal_dist(a)
    b_ = pairwise_internal_dist(b)

    i = torch.triu_indices(a_.shape[0], a_.shape[1], offset=1)
    mse = torch.nn.functional.mse_loss(a_[i[0], i[1]].float(), b_[i[0], i[1]].float())
    res = torch.sqrt(mse)

    return res


def rmsd(a, b):
    """Return the RMSD between two sets of coordinates."""
    t = pr.calcTransformation(a, b)
    return pr.calcRMSD(t.apply(a), b)


def pairwise_internal_dist(x):
    """Return all pairwise distances between points in a coordinate tensor.

    An implementation of cdist (pairwise distances between sets of vectors)
    from user jacobrgardner on github. Not implemented for batches.
    https://github.com/pytorch/pytorch/issues/15253

    Args:
        x (torch.Tensor): coordinate tensor with shape (L x 3)

    Returns:
        res (torch.Tensor): a distance tensor comparing all (L x L) pairs of
                            points
    """
    x1, x2 = x, x
    assert len(x1.shape) == 2, "Pairwise internal distance method is not " \
                               "implemented for batches."
    x1_norm = x1.pow(2).sum(
        dim=-1,
        keepdim=True)  # TODO: experiment with alternative to pow, remove duplicated norm
    res = torch.addmm(x1_norm.transpose(-2, -1), x1, x2.transpose(-2, -1),
                      alpha=-2).add_(x1_norm)
    res = res.clamp_min_(1e-30).sqrt_()
    return res


def angle_mse(true, pred):
    """Return the mean squared error between two tensor batches.

    Given a predicted angle tensor and a true angle tensor (batch-padded with
    nans, and missing-item-padded with nans), this function removes all nans before
    using torch's built-in MSE loss function.

    Args:
        pred, true (np.ndarray, torch.tensor): 3 or more dimensional tensors
    Returns:
        MSE loss between true and pred.
    """
    # # Remove batch padding
    # ang_non_zero = true.ne(0).any(dim=2)
    # tgt_ang_non_zero = true[ang_non_zero]

    # Remove missing angles
    ang_non_nans = ~true.isnan()
    return torch.nn.functional.mse_loss(pred[ang_non_nans], true[ang_non_nans])


def angle_mae(true, pred):
    """Compute flattened MeanAbsoluteError between 2 angle(Rad) tensors with nan pads."""
    absolute_error = torch.abs(angle_diff(true, pred))
    return torch.nanmean(absolute_error)


def angle_diff(true, pred):
    """Compute signed distance between two angle tensors (does not change shape)."""
    error = true - pred
    # Correct for out of bounds (wrap around)
    error[error > torch.pi] -= 2 * torch.pi
    error[error < -torch.pi] += 2 * torch.pi
    return error


def _tile(a, dim, n_tile):
    # https://discuss.pytorch.org/t/how-to-tile-a-tensor/13853/4
    init_dim = a.size(dim)
    repeat_idx = [1] * a.dim()
    repeat_idx[dim] = n_tile
    a = a.repeat(*(repeat_idx))
    order_index = torch.LongTensor(
        np.concatenate([init_dim * np.arange(n_tile) + i for i in range(init_dim)]))
    return torch.index_select(a, dim, order_index)