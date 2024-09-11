#******************************************************************#
# eval.py
# Adapted from original code from DETM
# Extracted the functionality for evaluating the DETM model from
# main.py to avoid misclicks and to streamline the process.
# Modifications required to "fix" generating the topic quality metric.

# USAGE:
# ||$ python eval.py --dataset jmr  --data_path data/JMR/split_paragraph_False --emb_path embeddings/JMR/skipgram_emb_300d.txt --theta_act relu --bow_norm 1 --batch_size 10 --min_df 10 --num_topics 30  --lr 0.001 --epochs 400 --load_from results/detm_jmr_K_30_Htheta_800_Optim_adam_Clip_0.0_ThetaAct_relu_Lr_0.001_Bsz_10_RhoSize_300_L_3_minDF_10_trainEmbeddings_1 --min_df 10  --mode eval
# ||$ python eval.py --dataset jm  --data_path data/JM/split_paragraph_False --emb_path embeddings/JM/skipgram_emb_300d.txt --theta_act relu --bow_norm 1 --batch_size 10 --min_df 10 --num_topics 30  --lr 0.001 --epochs 400 --load_from results/detm_jm_K_30_Htheta_800_Optim_adam_Clip_0.0_ThetaAct_relu_Lr_0.001_Bsz_10_RhoSize_300_L_3_minDF_10_trainEmbeddings_1 --min_df 10  --mode eval
# COMMAND CHANGES DEPENDING ON THE RESULTS USED
#******************************************************************#
#/usr/bin/python

from __future__ import print_function

import argparse
import pickle 
import numpy as np 
import os 
import math 
import random 
import sys
import matplotlib.pyplot as plt 
import seaborn as sns

import scipy.io

from sklearn.decomposition import PCA
from torch import optim
import torch
import data
from torch.nn import functional as F

from detm import DETM
from utils import nearest_neighbors, get_topic_coherence

parser = argparse.ArgumentParser(description='The Embedded Topic Model')

### data and file related arguments
parser.add_argument('--dataset', type=str, default='un', help='name of corpus')
parser.add_argument('--data_path', type=str, default='un/', help='directory containing data')
parser.add_argument('--emb_path', type=str, default='skipgram/embeddings.txt', help='directory containing embeddings')
parser.add_argument('--save_path', type=str, default='./results', help='path to save results')
parser.add_argument('--batch_size', type=int, default=1000, help='number of documents in a batch for training')
parser.add_argument('--min_df', type=int, default=100, help='to get the right data..minimum document frequency')

### model-related arguments
parser.add_argument('--num_topics', type=int, default=50, help='number of topics')
parser.add_argument('--rho_size', type=int, default=300, help='dimension of rho')
parser.add_argument('--emb_size', type=int, default=300, help='dimension of embeddings')
parser.add_argument('--t_hidden_size', type=int, default=800, help='dimension of hidden space of q(theta)')
parser.add_argument('--theta_act', type=str, default='relu', help='tanh, softplus, relu, rrelu, leakyrelu, elu, selu, glu)')
parser.add_argument('--train_embeddings', type=int, default=1, help='whether to fix rho or train it')
parser.add_argument('--eta_nlayers', type=int, default=3, help='number of layers for eta')
parser.add_argument('--eta_hidden_size', type=int, default=200, help='number of hidden units for rnn')
parser.add_argument('--delta', type=float, default=0.005, help='prior variance')

### optimization-related arguments
parser.add_argument('--lr', type=float, default=0.005, help='learning rate')
parser.add_argument('--lr_factor', type=float, default=4.0, help='divide learning rate by this')
parser.add_argument('--epochs', type=int, default=100, help='number of epochs to train')
parser.add_argument('--mode', type=str, default='train', help='train or eval model')
parser.add_argument('--optimizer', type=str, default='adam', help='choice of optimizer')
parser.add_argument('--seed', type=int, default=5022024 , help='random seed (default: 1)')
parser.add_argument('--enc_drop', type=float, default=0.0, help='dropout rate on encoder')
parser.add_argument('--eta_dropout', type=float, default=0.0, help='dropout rate on rnn for eta')
parser.add_argument('--clip', type=float, default=0.0, help='gradient clipping')
parser.add_argument('--nonmono', type=int, default=10, help='number of bad hits allowed')
parser.add_argument('--wdecay', type=float, default=1.2e-6, help='some l2 regularization')
parser.add_argument('--anneal_lr', type=int, default=0, help='whether to anneal the learning rate or not')
parser.add_argument('--bow_norm', type=int, default=1, help='normalize the bows or not')


### evaluation, visualization, and logging-related arguments
parser.add_argument('--num_words', type=int, default=20, help='number of words for topic viz')
parser.add_argument('--log_interval', type=int, default=10, help='when to log training')
parser.add_argument('--visualize_every', type=int, default=1, help='when to visualize results')
parser.add_argument('--eval_batch_size', type=int, default=1000, help='input batch size for evaluation')
parser.add_argument('--load_from', type=str, default='', help='the name of the ckpt to eval from')
parser.add_argument('--tc', type=int, default=0, help='whether to compute tc or not')

args = parser.parse_args()

pca = PCA(n_components=2)

device = "cpu" #torch.device("mps" if torch.backend.mps.is_built() else "cpu")
print(device)

## set seed
np.random.seed(args.seed)
torch.backends.cudnn.deterministic = True
torch.manual_seed(args.seed)

## get data
# 1. vocabulary
print('Getting vocabulary ...')
data_file = os.path.join(args.data_path, 'min_df_{}'.format(args.min_df))
vocab, train, valid, test = data.get_data(data_file, temporal=True)
vocab_size = len(vocab)
args.vocab_size = vocab_size

# 1. training data
print('Getting training data ...')
train_tokens = train['tokens']
train_counts = train['counts']
train_times = train['times']
args.num_times = len(np.unique(train_times))
args.num_docs_train = len(train_tokens)
train_rnn_inp = data.get_rnn_input(
    train_tokens, train_counts, train_times, args.num_times, args.vocab_size, args.num_docs_train)

# 2. dev set
print('Getting validation data ...')
valid_tokens = valid['tokens']
valid_counts = valid['counts']
valid_times = valid['times']
args.num_docs_valid = len(valid_tokens)
valid_rnn_inp = data.get_rnn_input(
    valid_tokens, valid_counts, valid_times, args.num_times, args.vocab_size, args.num_docs_valid)

# 3. test data
print('Getting testing data ...')
test_tokens = test['tokens']
test_counts = test['counts']
test_times = test['times']
args.num_docs_test = len(test_tokens)
test_rnn_inp = data.get_rnn_input(
    test_tokens, test_counts, test_times, args.num_times, args.vocab_size, args.num_docs_test)

test_1_tokens = test['tokens_1']
test_1_counts = test['counts_1']
test_1_times = test_times
args.num_docs_test_1 = len(test_1_tokens)
test_1_rnn_inp = data.get_rnn_input(
    test_1_tokens, test_1_counts, test_1_times, args.num_times, args.vocab_size, args.num_docs_test)

test_2_tokens = test['tokens_2']
test_2_counts = test['counts_2']
test_2_times = test_times
args.num_docs_test_2 = len(test_2_tokens)
test_2_rnn_inp = data.get_rnn_input(
    test_2_tokens, test_2_counts, test_2_times, args.num_times, args.vocab_size, args.num_docs_test)

## get embeddings 
print('Getting embeddings ...')
emb_path = args.emb_path
vect_path = os.path.join(args.data_path.split('/')[0], 'embeddings.pkl')   
vectors = {}
with open(emb_path, 'rb') as f:
    for l in f:
        line = l.decode().split()
        word = line[0]
        if word in vocab:
            vect = np.array(line[1:]).astype(float) #MODIFICATION np.float -> float, deprecated 
            vectors[word] = vect
embeddings = np.zeros((vocab_size, args.emb_size))

words_found = 0
for i, word in enumerate(vocab):
    try: 
        embeddings[i] = vectors[word]
        words_found += 1
    except KeyError:
        embeddings[i] = np.random.normal(scale=0.6, size=(args.emb_size, ))
embeddings = embeddings.astype('float') #MODIFICATION - "TypeError: Cannot convert a MPS Tensor to float64 dtype as the MPS framework doesn't support float64. Please use float32 instead."
embeddings = torch.from_numpy(embeddings).to(device)
args.embeddings_dim = embeddings.size()
print(embeddings)
print('\n')
print('=*'*100)
print('Training a Dynamic Embedded Topic Model on {} with the following settings: {}'.format(args.dataset.upper(), args))
print('=*'*100)


## define checkpoint
if not os.path.exists(args.save_path):
    os.makedirs(args.save_path)

if args.mode == 'eval':
    ckpt = args.load_from
else:
    ckpt = os.path.join(args.save_path, 
        'detm_{}_K_{}_Htheta_{}_Optim_{}_Clip_{}_ThetaAct_{}_Lr_{}_Bsz_{}_RhoSize_{}_L_{}_minDF_{}_trainEmbeddings_{}'.format(
        args.dataset, args.num_topics, args.t_hidden_size, args.optimizer, args.clip, args.theta_act, 
            args.lr, args.batch_size, args.rho_size, args.eta_nlayers, args.min_df, args.train_embeddings))

## define model and optimizer
if args.load_from != '':
    print('Loading checkpoint from {}'.format(args.load_from))
    with open(args.load_from, 'rb') as f:
        model = torch.load(f)
else:
    model = DETM(args, embeddings)
print('\nDETM architecture: {}'.format(model))
model.to(device)

if args.optimizer == 'adam':
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.wdecay)
elif args.optimizer == 'adagrad':
    optimizer = optim.Adagrad(model.parameters(), lr=args.lr, weight_decay=args.wdecay)
elif args.optimizer == 'adadelta':
    optimizer = optim.Adadelta(model.parameters(), lr=args.lr, weight_decay=args.wdecay)
elif args.optimizer == 'rmsprop':
    optimizer = optim.RMSprop(model.parameters(), lr=args.lr, weight_decay=args.wdecay)
elif args.optimizer == 'asgd':
    optimizer = optim.ASGD(model.parameters(), lr=args.lr, t0=0, lambd=0., weight_decay=args.wdecay)
else:
    print('Defaulting to vanilla SGD')
    optimizer = optim.SGD(model.parameters(), lr=args.lr)

def visualize():
    """Visualizes topics and embeddings and word usage evolution.
    """
    model.eval()
    with torch.no_grad():
        alpha = model.mu_q_alpha
        beta = model.get_beta(alpha) 
        print('beta: ', beta.size())
        print('\n')
        print('#'*100)
        print('Visualize topics...')
        times = [0, 10, 36] #MODIFICATION - 0, 10, 40
        topics_words = []
        for k in range(args.num_topics):
            for t in times:
                gamma = beta[k, t, :]
                top_words = list(gamma.cpu().numpy().argsort()[-args.num_words+1:][::-1])
                topic_words = [vocab[a] for a in top_words]
                topics_words.append(' '.join(topic_words))
                print('Topic {} .. Time: {} ===> {}'.format(k, t, topic_words)) 

        print('\n')

        # print('Visualize word embeddings ...')
        # queries = ['economic', 'assembly', 'security', 'management', 'debt', 'rights',  'africa']
        # try:
        #     embeddings = model.rho.weight  # Vocab_size x E
        # except:
        #     embeddings = model.rho         # Vocab_size x E
        # neighbors = []
        # for word in queries:
        #     print('word: {} .. neighbors: {}'.format(
        #         word, nearest_neighbors(word, embeddings, vocab, args.num_words)))
        # print('#'*100)

        # print('\n')
        # print('Visualize word evolution ...')
        # topic_0 = None ### k 
        # queries_0 = ['woman', 'gender', 'man', 'mankind', 'humankind'] ### v 

        # topic_1 = None
        # queries_1 = ['africa', 'colonial', 'racist', 'democratic']

        # topic_2 = None
        # queries_2 = ['poverty', 'sustainable', 'trade']

        # topic_3 = None
        # queries_3 = ['soviet', 'convention', 'iran']

        # topic_4 = None # climate
        # queries_4 = ['environment', 'impact', 'threats', 'small', 'global', 'climate']

def _eta_helper(rnn_inp):
    inp = model.q_eta_map(rnn_inp).unsqueeze(1)
    hidden = model.init_hidden()
    output, _ = model.q_eta(inp, hidden)
    output = output.squeeze()
    etas = torch.zeros(model.num_times, model.num_topics).to(device)
    inp_0 = torch.cat([output[0], torch.zeros(model.num_topics,).to(device)], dim=0)
    etas[0] = model.mu_q_eta(inp_0)
    for t in range(1, model.num_times):
        inp_t = torch.cat([output[t], etas[t-1]], dim=0)
        etas[t] = model.mu_q_eta(inp_t)
    return etas

def get_eta(source):
    model.eval()
    with torch.no_grad():
        if source == 'val':
            rnn_inp = valid_rnn_inp
            return _eta_helper(rnn_inp)
        else:
            rnn_1_inp = test_1_rnn_inp
            return _eta_helper(rnn_1_inp)

def get_theta(eta, bows):
    model.eval()
    with torch.no_grad():
        inp = torch.cat([bows, eta], dim=1)
        q_theta = model.q_theta(inp)
        mu_theta = model.mu_q_theta(q_theta)
        theta = F.softmax(mu_theta, dim=-1)
        return theta    

def get_completion_ppl(source):
    """Returns document completion perplexity.
    """
    model.eval()
    with torch.no_grad():
        alpha = model.mu_q_alpha
        if source == 'val':
            indices = torch.split(torch.tensor(range(args.num_docs_valid)), args.eval_batch_size)
            tokens = valid_tokens
            counts = valid_counts
            times = valid_times

            eta = get_eta('val')

            acc_loss = 0
            cnt = 0
            for idx, ind in enumerate(indices):
                data_batch, times_batch = data.get_batch(
                    tokens, counts, ind, args.vocab_size, args.emb_size, temporal=True, times=times)
                sums = data_batch.sum(1).unsqueeze(1)
                if args.bow_norm:
                    normalized_data_batch = data_batch / sums
                else:
                    normalized_data_batch = data_batch

                eta_td = eta[times_batch.type('torch.LongTensor')]
                #print('eta_td: ', eta_td,eta_td.size())
                theta = get_theta(eta_td, normalized_data_batch)
                print('eta_td: ', eta_td, eta_td.size())    
                print('normalized_data_batch: ', normalized_data_batch, normalized_data_batch.size())   
                print('theta: ', theta, theta.size())
                input("Press Enter to continue...")
                alpha_td = alpha[:, times_batch.type('torch.LongTensor'), :]
                beta = model.get_beta(alpha_td).permute(1, 0, 2)
                loglik = theta.unsqueeze(2) * beta
                loglik = loglik.sum(1)
                loglik = torch.log(loglik)
                nll = -loglik * data_batch
                nll = nll.sum(-1)
                loss = nll / sums.squeeze()
                loss = loss.mean().item()
                acc_loss += loss
                cnt += 1
            cur_loss = acc_loss / cnt

            ppl_all = round(math.exp(cur_loss), 1)
            print('*'*100)
            print('{} PPL: {}'.format(source.upper(), ppl_all))
            print('*'*100)
            return ppl_all
        else: 
            indices = torch.split(torch.tensor(range(args.num_docs_test)), args.eval_batch_size)
            tokens_1 = test_1_tokens
            counts_1 = test_1_counts

            tokens_2 = test_2_tokens
            counts_2 = test_2_counts

            eta_1 = get_eta('test')

            acc_loss = 0
            cnt = 0
            indices = torch.split(torch.tensor(range(args.num_docs_test)), args.eval_batch_size)
            for idx, ind in enumerate(indices):
                data_batch_1, times_batch_1 = data.get_batch(
                    tokens_1, counts_1, ind, args.vocab_size, args.emb_size, temporal=True, times=test_times)
                sums_1 = data_batch_1.sum(1).unsqueeze(1)
                if args.bow_norm:
                    normalized_data_batch_1 = data_batch_1 / sums_1
                else:
                    normalized_data_batch_1 = data_batch_1

                eta_td_1 = eta_1[times_batch_1.type('torch.LongTensor')]
                theta = get_theta(eta_td_1, normalized_data_batch_1)

                data_batch_2, times_batch_2 = data.get_batch(
                    tokens_2, counts_2, ind, args.vocab_size, args.emb_size, temporal=True, times=test_times)
                sums_2 = data_batch_2.sum(1).unsqueeze(1)

                alpha_td = alpha[:, times_batch_2.type('torch.LongTensor'), :]
                beta = model.get_beta(alpha_td).permute(1, 0, 2)
                loglik = theta.unsqueeze(2) * beta
                loglik = loglik.sum(1)
                loglik = torch.log(loglik)
                nll = -loglik * data_batch_2
                nll = nll.sum(-1)
                loss = nll / sums_2.squeeze()
                loss = loss.mean().item()
                acc_loss += loss
                cnt += 1
            cur_loss = acc_loss / cnt
            ppl_dc = round(math.exp(cur_loss), 1)
            print('*'*100)
            print('{} Doc Completion PPL: {}'.format(source.upper(), ppl_dc))
            print('*'*100)
            return ppl_dc

def _diversity_helper(beta, num_tops):
    list_w = np.zeros((args.num_topics, num_tops))
    for k in range(args.num_topics):
        gamma = beta[k, :]
        top_words = gamma.cpu().numpy().argsort()[-num_tops:][::-1]
        list_w[k, :] = top_words
    list_w = np.reshape(list_w, (-1))
    list_w = list(list_w)
    n_unique = len(np.unique(list_w))
    diversity = n_unique / (args.num_topics * num_tops)
    return diversity

def get_topic_quality():
    """Returns topic coherence and topic diversity.
    """
    model.eval()
    with torch.no_grad():
        alpha = model.mu_q_alpha
        beta = model.get_beta(alpha) 
        print('beta: ', beta.size())

        print('\n')
        print('#'*100)
        print('Get topic diversity...')
        num_tops = 25
        TD_all = np.zeros((args.num_times,))
        for tt in range(args.num_times):
            TD_all[tt] = _diversity_helper(beta[:, tt, :], num_tops)
        TD = np.mean(TD_all)
        print('Topic Diversity is: {}'.format(TD))

        print('\n')
        print('Get topic coherence...')
        print('train_tokens: ', train_tokens[0])
        TC_all = []
        cnt_all = []
        for tt in range(args.num_times):
            tc, cnt = get_topic_coherence(beta[:, tt, :].cpu().numpy(), train_tokens, vocab)
            TC_all.append(tc)
            cnt_all.append(cnt)
        print('TC_all: ', TC_all)
        TC_all = torch.tensor(TC_all)
        print('TC_all: ', TC_all.size())
        print('\n')
        print('Get topic quality...')
        #MODIFICATION - tc * diversity
        print('TC_all: ', TC_all)
        print('TD_all: ', TD_all)
        # quality = 0
        # for i in range(TC_all.size(0)):
        #     quality += (TC_all[i] * TD_all[i])
        quality = np.mean(TC_all) * np.mean(TD_all)
        print('Topic Quality is: {}'.format(quality))
        print('#'*100)

        return TC_all, TD_all



if args.mode == 'eval':
    #do nothing
    with open(ckpt, 'rb') as f:
        model = torch.load(f)
    model = model.to(device)
        
    print('saving alpha...')
    with torch.no_grad():
        alpha = model.mu_q_alpha.cpu().numpy()
        scipy.io.savemat(ckpt+'_alpha.mat', {'values': alpha}, do_compression=True)


    # print('saving theta...')
    # with torch.no_grad():
    #     theta = get_theta(bows, times)
    #     scipy.io.savemat(ckpt+'_theta.mat', {'values': theta}, do_compression=True)

    print('computing validation perplexity...')
    val_ppl = get_completion_ppl('val')
    #print('computing test perplexity...')
    #test_ppl = get_completion_ppl('test')
    print('computing topic coherence and topic diversity...')
    tc, td = get_topic_quality()
    print('Topic Quality' + '' + tc * td)
    #print('visualizing topics and embeddings...')
    #visualize()

print('Done!')