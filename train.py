#!/usr/bin/env python

"""
This script is used to train models.

Contributors: Ambroise Odonnat and Theo Gnassounou.
"""

import argparse
import os
from platform import architecture
import numpy as np
import pandas as pd

from loguru import logger
from torch import nn
from torch.optim import Adam

from models.architectures import RNN_self_attention, STT
from models.training import make_model
from loader.dataloader import Loader
from loader.data import Data
from utils.cost_sensitive_loss import get_criterion
from utils.utils_ import define_device, get_pos_weight, reset_weights
from utils.select_subject import select_subject

def get_parser():

    """ Set parameters for the experiment."""

    parser = argparse.ArgumentParser(
        "Spike detection", description="Spike detection using attention layer"
    )
    parser.add_argument("--path_root", type=str, default="../BIDSdataset/")
    parser.add_argument("--method", type=str, default="RNN_self_attention")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--n_epochs", type=int, default=100)
    parser.add_argument("--n_subjects", type=int, default=5)
    parser.add_argument("--weight_loss", action="store_true")
    parser.add_argument("--cost_sensitive", action="store_true")
    parser.add_argument("--lambd", type=float, default=1e-4)
    parser.add_argument("--len_trials", type=float, default=2)
    parser.add_argument("--mix_up", action="store_true")
    parser.add_argument("--beta", type=float, default=0.4)

    return parser


# Experiment name
parser = get_parser()
args = parser.parse_args()
path_root = args.path_root
method = args.method
save = args.save
batch_size = args.batch_size
num_workers = args.num_workers
n_epochs = args.n_epochs
n_subjects = args.n_subjects
weight_loss = args.weight_loss
cost_sensitive = args.cost_sensitive
lambd = args.lambd
len_trials = args.len_trials
mix_up = args.mix_up
beta = args.beta

# Recover params
gpu_id = 0
weight_decay = 0
lr = 1e-3  # Learning rate
patience = 10

# Define device
available, device = define_device(gpu_id)

# Recover results
results = []
mean_acc, mean_f1, mean_precision, mean_recall = 0, 0, 0, 0
steps = 0

# Recover dataset
assert method in ("RNN_self_attention", "transformer_classification",
                  "transformer_detection")
logger.info(f"Method used: {method}")

if method == 'RNN_self_attention':
    single_channel = True
else:
    single_channel = False

path_subject_info = (
    "../results/info_subject_{}".format(len_trials)
)
selected_subjects = select_subject(n_subjects, path_subject_info, path_root, len_trials)

dataset = Data(path_root, 'spikeandwave', selected_subjects, len_trials=len_trials)
data, labels, annotated_channels = dataset.all_datasets()
subject_ids = np.asarray(list(data.keys()))


# Define loss
criterion = nn.BCEWithLogitsLoss().to(device)

for seed in range(5):

    # Dataloader

    # Labels are the spike events times
    loader = Loader(data,
                    labels,
                    annotated_channels,
                    single_channel=single_channel,
                    batch_size=batch_size,
                    subject_LOPO=None,
                    num_workers=num_workers,
                    )

    train_loader, val_loader, test_loader, train_labels = loader.load()

    # Define architecture
    if method == "RNN_self_attention":
        n_time_points = len(data[subject_ids[0]][0][0][0])
        architecture = RNN_self_attention(n_time_points=n_time_points)
    elif method == "transformer_classification":
        n_time_points = len(data[subject_ids[0]][0][0][0])
        architecture = STT(n_time_points=n_time_points)
    architecture.apply(reset_weights)

    if weight_loss:
        pos_weight = get_pos_weight([[train_labels]]).to(device)
        train_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        train_criterion = train_criterion.to(device)
    else:
        train_criterion = criterion
    train_criterion = get_criterion(train_criterion,
                                    cost_sensitive,
                                    lambd)

    # Define optimizer
    optimizer = Adam(architecture.parameters(), lr=lr,
                     weight_decay=weight_decay)

    # Define training pipeline
    architecture = architecture.to(device)

    model = make_model(architecture,
                       train_loader,
                       val_loader,
                       test_loader,
                       optimizer,
                       train_criterion,
                       criterion,
                       single_channel,
                       n_epochs=n_epochs,
                       patience=patience,
                       mix_up=mix_up,
                       beta=beta)

    # Train Model
    history = model.train()

    if not os.path.exists("../results"):
        os.mkdir("../results")

    # Compute test performance and save it
    acc, f1, precision, recall = model.score()
    results.append(
        {
            "method": method,
            "mix_up": mix_up,
            "weight_loss": weight_loss,
            "cost_sensitive": cost_sensitive,
            "len_trials": len_trials,
            "fold": seed,
            "acc": acc,
            "f1": f1,
            "precision": precision,
            "recall": recall
        }
    )
    mean_acc += acc
    mean_f1 += f1
    mean_precision += precision
    mean_recall += recall
    steps += 1
    if save:

        # Save results file as csv
        if not os.path.exists("../results"):
            os.mkdir("../results")

        results_path = (
            "../results/csv_len_trial"
        )
        if not os.path.exists(results_path):
            os.mkdir(results_path)

        df_results = pd.DataFrame(results)
        df_results.to_csv(
            os.path.join(results_path,
                         "accuracy_results_spike_detection_method-{}"
                         "_mix-up-{}_weight-loss-{}_cost-sensitive-{}_{}"
                         "-subjects.csv".format(method,
                                                mix_up,
                                                weight_loss,
                                                cost_sensitive,
                                                len(subject_ids))
                         )
            )
print("Mean accuracy \t Mean F1-score \t Mean precision \t Mean recall")
print("-" * 80)
print(
    f"{mean_acc/steps:0.4f} \t {mean_f1/steps:0.4f} \t"
    f"{mean_precision/steps:0.4f} \t {mean_recall/steps:0.4f}\n"
)
