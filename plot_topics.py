import scipy.io 
import matplotlib.pyplot as plt 
import data 
import pickle 
import numpy as np 
import sys
from sklearn.decomposition import PCA
from mpl_toolkits.mplot3d import Axes3D
import argparse

CLI = argparse.ArgumentParser()
CLI.add_argument(
    "--corpus",
    type=str,
    default="JMR",
    help="Corpus to use (JM or JMR)"
)
CLI.add_argument(
    "--dim",
    type=str,
    default="2",
    help="Dimension of PCA (2 or 3)"
)
CLI.add_argument(
    "--list",
    type=float,
    nargs='*',
    default=[],
    help="List of topics to plot"
)

args = CLI.parse_args()

use = 'JM' if args.corpus == 'JM' else 'JMR'

if use == 'JM':
    beta = scipy.io.loadmat('./results/detm_jm_K_30_Htheta_800_Optim_adam_Clip_0.0_ThetaAct_relu_Lr_0.001_Bsz_10_RhoSize_300_L_3_minDF_10_trainEmbeddings_1_beta.mat')['values']
    timestamps = 'data/JM/split_paragraph_False/min_df_10/timestamps.pkl'
    data_file = 'data/JM/split_paragraph_False/min_df_10'
    shift_value = 1936
else:
    beta = scipy.io.loadmat('./results/detm_jmr_K_30_Htheta_800_Optim_adam_Clip_0.0_ThetaAct_relu_Lr_0.001_Bsz_10_RhoSize_300_L_3_minDF_10_trainEmbeddings_1_beta.mat')['values']
    timestamps = 'data/JMR/split_paragraph_False/min_df_10/timestamps.pkl'
    data_file = 'data/JMR/split_paragraph_False/min_df_10'
    shift_value = 1963
print('beta: ', beta.shape)

# Load timestamps
with open(timestamps, 'rb') as f:
    timelist = pickle.load(f)

# Number of topics (K), timestamps (T), vocabulary size (V)
K, T, V = beta.shape

# Option 1: Flatten the time axis to analyze overall topic distribution across all time points
beta_flat = beta.reshape(K, -1)  # Shape: K x (T * V)

if args.list == []:
    if args.dim == '2':
        # Apply PCA
        pca = PCA(n_components=2)
        beta_pca = pca.fit_transform(beta_flat)

        # Plotting the results in 2D
        plt.figure(figsize=(10, 8))
        plt.scatter(beta_pca[:, 0], beta_pca[:, 1], s=100, c='red')

        # Annotate each point with the topic number
        for i in range(K):
            plt.text(beta_pca[i, 0], beta_pca[i, 1], f'{i}', fontsize=12)

        plt.title(f'PCA of Topics in {use}')
        plt.grid(True)
        plt.show()
    else:
        # Apply PCA
        pca = PCA(n_components=3)
        beta_pca = pca.fit_transform(beta_flat)

        fig = plt.figure(figsize=(10, 8))
        ax = fig.add_subplot(111, projection='3d')
        ax.scatter(beta_pca[:, 0], beta_pca[:, 1], beta_pca[:, 2], s=100, c='blue')
        for i in range(K):
            ax.text(beta_pca[i, 0], beta_pca[i, 1], beta_pca[i, 2], f'Topic {i}', fontsize=12)

        plt.title(f'3D PCA of Topics in {use}')
        plt.show()

else:
    # Plot topics from the list in args.list, across each timestamp and linked by a line
    topics_to_plot = [int(i) for i in args.list] if args.list[0] != -1 else range(K)
    
    if args.dim == '2':
        plt.figure(figsize=(12, 10))
        
        # Loop over each topic
        for k in topics_to_plot:
            # Apply PCA at each timestamp
            pca_results = np.zeros((T, 2))
            for t in range(T):
                pca = PCA(n_components=2)
                pca_results[t, :] = pca.fit_transform(beta[:, t, :])[k]

            # Plot each topic's trajectory over time
            plt.plot(pca_results[:, 0], pca_results[:, 1], marker='o', label=f'Topic {k}')
        
        # Annotate the first and last points
        for k in topics_to_plot:
            plt.text(pca_results[0, 0], pca_results[0, 1], f'{k} (start)', fontsize=8, color='red')
            plt.text(pca_results[-1, 0], pca_results[-1, 1], f'{k} (end)', fontsize=8, color='blue')

        plt.title(f'PCA of Selected Topics in {use} Over Time')
        plt.legend(loc='best', fontsize='small')
        plt.grid(True)
        plt.show()
        
    else:
        fig = plt.figure(figsize=(12, 10))
        ax = fig.add_subplot(111, projection='3d')

        # Loop over each topic
        for k in topics_to_plot:
            # Apply PCA at each timestamp
            pca_results = np.zeros((T, 3))
            for t in range(T):
                pca = PCA(n_components=3)
                pca_results[t, :] = pca.fit_transform(beta[:, t, :])[k]
            
            # Plot each topic's trajectory over time
            ax.plot(pca_results[:, 0], pca_results[:, 1], pca_results[:, 2], marker='o', label=f'Topic {k}')
        
        # Annotate the first and last points
        for k in topics_to_plot:
            ax.text(pca_results[0, 0], pca_results[0, 1], pca_results[0, 2], f'{k} (start)', fontsize=8, color='red')
            ax.text(pca_results[-1, 0], pca_results[-1, 1], pca_results[-1, 2], f'{k} (end)', fontsize=8, color='blue')
        
        plt.title(f'3D PCA of Selected Topics in {use} Over Time')
        plt.legend(loc='best', fontsize='small')
        plt.show()