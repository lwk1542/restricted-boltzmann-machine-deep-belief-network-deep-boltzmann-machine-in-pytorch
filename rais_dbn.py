import torch
import numpy as np
from torch.autograd import Variable
from joblib import Parallel, delayed
import multiprocessing

class DBN(object):
    def __init__(self, n_visible = 784, n_hidden = [500,500], W = None, v_bias = None, h_bias=None,
                 batch_size = 30, trained = False):
        self.rbm_layers = []
        self.n_layers = len(n_hidden)
        
        for i in range(self.n_layers):
            if i == 0:
                input_size = n_visible
            else:
                input_size = n_hidden[i-1]
            if trained:
                rbm = RBM(n_visible = input_size, 
                              n_hidden = n_hidden[i],
                              W = W[i],
                              h_bias = h_bias[i],
                              v_bias = v_bias[i],
                              batch_size = batch_size)
            else:
                rbm = RBM(n_visible = input_size, 
                              n_hidden = n_hidden[i],
                              batch_size = batch_size)
            self.rbm_layers.append(rbm)

    
class RBM(object):
    
    def __init__(self, n_visible = 784, n_hidden = 500, W = None, v_bias = None, 
                 h_bias = None, batch_size = 0):
        
        self.n_visible = n_visible
        self.n_hidden = n_hidden
        self.batch_size = batch_size
        self.logZ = None
        if not W.any():
            initial_W = np.asarray(
                np.random.normal(loc = 0, scale = 1/n_visible,
                    size=(n_visible, n_hidden)
                    ),
                )
            W = initial_W
            
        if not v_bias.any():
            v_bias = np.zeros((1,n_visible))

        if not h_bias.any():
            h_bias = np.zeros((1,n_hidden))
            
        self.W = W
        self.v_bias = v_bias
        self.h_bias = h_bias


    def free_energy(self, v_sample, W):
        
        num = len(v_sample)
        Wv = np.clip(np.matmul(v_sample,W) + self.h_bias,-80,80)
        hidden = np.log(1+np.exp(Wv)).sum(1)
        vbias = np.matmul(v_sample, self.v_bias.T).reshape(len(hidden))
        return -hidden.reshape(num)-vbias.reshape(num)


    
    def free_energy_hidden(self, h_sample, W):
        num = len(h_sample)
        Wh = np.matmul(h_sample, W.T) + self.v_bias
        hidden = np.log(1+np.exp(Wh)).sum(1)
        hbias = np.matmul(h_sample, self.h_bias.T).reshape(len(hidden))
        return -hidden.reshape(num) - hbias.reshape(num)
    
    def sample_h_given_v(self, v0_sample, W,h_bias):
        
        activation = np.matmul(v0_sample,W) + h_bias
        h1_mean = 1/(1+np.exp(-np.clip(activation,-100,100)))
        h1_sample = np.random.binomial(1, p=h1_mean)

        return [h1_sample, h1_mean]

    
    def sample_v_given_h(self, h0_sample, W, h_bias):

        activation = np.matmul(h0_sample, W.T) + self.v_bias
        v1_mean = 1/(1+np.exp(-np.clip(activation,-100,100)))
        v1_sample = np.random.binomial(1, p=v1_mean)
        return [v1_sample, v1_mean]

    
    def gibbs_hvh(self, h0_sample, W, h_bias):
        v1_sample, v1_mean = self.sample_v_given_h(h0_sample, W, h_bias)
        h1_sample, p_h1 = self.sample_h_given_v(v1_sample, W, h_bias)
        
        return [v1_sample, h1_sample, p_h1] 
    
    def gibbs_vhv(self, v0_sample, W, h_bias):
        h1_sample, h1_mean = self.sample_h_given_v(v0_sample, W, h_bias)
        v1_sample, p_v1 = self.sample_v_given_h(h1_sample, W, h_bias)
        
        return [h1_sample, v1_sample, p_v1]
        
    
    def rais(self, data, step = 1000, M = 100, parallel = False, seed = None):
        num_data = data.shape[0]
        result = 0
        if not parallel:
            p = []
            for i in range(M):
                logw = self.mcmc_r(data, step, num_data)
                p.append(logw)
            
            p = np.array(p)
            logmeanp = logmeanexp(p, axis = 0)
        else:
            num_cores = multiprocessing.cpu_count()

            p = Parallel(n_jobs=num_cores)(delayed(self.mcmc_r)(v = data, step = step, num_data = num_data, seed = seed) for i in range(M))
            
            p = np.array(p)
            
            logmeanp = logmeanexp(p, axis = 0)
            
        result = logmeanp.mean()
        
        return result
        
    def mcmc_r(self, v, step, num_data, seed = None):
        np.random.seed(seed)
        logZ0 = np.log((1+np.exp(self.v_bias))).sum() + np.log(1+np.exp(self.h_bias)).sum()        
        #h = self.sample_h_given_v(v, self.W, self.h_bias)
        logw = -self.free_energy(v,self.W) - logZ0
        for k in range(step-1,-1,-1):
            a,v,c = self.gibbs_vhv(v, (k)*1.0/step*self.W, self.h_bias)
            logp_k = -self.free_energy(v, k*1.0/step*self.W)
            logp_k1 = -self.free_energy(v, (k+1)*1.0/step*self.W)  
            logw += logp_k - logp_k1
           
        return logw.reshape(num_data)
    
    def get_logZ(self, dbn, data, step = 1000, M = 100, parallel = False):
        
        for i in range(dbn.n_layers-1):
            data = dbn.rbm_layers[i].sample_h_given_v(data, dbn.rbm_layers[i].W, dbn.rbm_layers[i].h_bias)[0]
    
        self.logZ = -self.rais(data = data, step = step, M = M, parallel = parallel) - self.free_energy(data, self.W).mean()
        return self.logZ
    
def logp_ais(trained_model, v_input, step = 1000, M_Z = 100, M_IS = 100, parallel = False):
    W = [i.W.data.numpy() for i in trained_model.rbm_layers]
    v_bias = [i.v_bias.data.numpy() for i in trained_model.rbm_layers]
    h_bias = [i.h_bias.data.numpy() for i in trained_model.rbm_layers]
    n_visible = W[0].shape[0]
    n_hidden = [i.shape[1] for i in W]
    dbn = DBN(n_visible = n_visible, n_hidden = n_hidden, W = W, v_bias = v_bias, h_bias = h_bias, trained = True)
    dbn.rbm_layers[-1].get_logZ(dbn = dbn, data = v_input, step = step, M = M_Z, parallel = parallel)
    logw_ulogprob = ulogprob(v_input, dbn, M = M_IS, parallel = parallel)
    return logw_ulogprob.mean() - dbn.rbm_layers[-1].logZ

def ulogprob(v_input, dbn, M = 1000, parallel = False):
    logw = np.zeros([M, len(v_input)])
    # samples = v_input
    if not parallel:
        for i in range(M):
            # samples = v_input
            # for l in range(dbn.n_layers-1):
            #     logw[i,:] += -dbn.rbm_layers[l].free_energy(samples,dbn.rbm_layers[l].W)[0]
            #     samples = dbn.rbm_layers[l].sample_h_given_v(samples,dbn.rbm_layers[l].W,dbn.rbm_layers[l].h_bias)[0]
            #     logw[i,:] -= -dbn.rbm_layers[l].free_energy_hidden(samples,dbn.rbm_layers[l].W)[0]
            # logw[i,:] += -dbn.rbm_layers[-1].free_energy(samples,dbn.rbm_layers[-1].W)[0]
            logw[i,:] += important_sampling(v_input, dbn)
    else:
        num_cores = multiprocessing.cpu_count()

        results = Parallel(n_jobs=num_cores)(delayed(important_sampling)(v_input = v_input, dbn = dbn) for i in range(M))
        logw += np.asarray(results)
           
    return logmeanexp(logw,0)

def important_sampling(v_input, dbn):
    samples = v_input
    logw = np.zeros(len(v_input))
    for l in range(dbn.n_layers-1):
        logw += -dbn.rbm_layers[l].free_energy(samples,dbn.rbm_layers[l].W)
        samples = dbn.rbm_layers[l].sample_h_given_v(samples,dbn.rbm_layers[l].W,dbn.rbm_layers[l].h_bias)[0]
        logw -= -dbn.rbm_layers[l].free_energy_hidden(samples,dbn.rbm_layers[l].W)
    logw += -dbn.rbm_layers[-1].free_energy(samples,dbn.rbm_layers[-1].W)
    return logw

def logmeanexp(x, axis=None):
    
    x = np.asmatrix(x)
    if not axis:
        n = len(x)
    else:
        n = x.shape[axis]
    
    x_max = x.max(axis)
    return (x_max + np.log(np.exp(x-x_max).sum(axis)) - np.log(n)).A