import tensorflow as tf
import tensorflow_probability as tfp
import os
import numpy as np

from runner import main

np.warnings.filterwarnings('ignore')          # to avoid np deprecation warning
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"      # to avoid lots of log about the device
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'   # hack to avoid OS bug...

print("the code is written in:")
print("\t tensorflow version: 1.12.0")
print("\t tensorflow_probability version: 0.5.0")

print("the system uses:")
print("\t tensorflow version:", tf.__version__)
print("\t tensorflow_probability version:", tfp.__version__)


# --------------------- training hyperparameters --------------------- #
Dx = 2
Dy = 1
n_particles = 32

batch_size = 1
lr = 3e-3
epoch = 200
seed = 0

# ------------------- data set parameters ------------------ #
# generate synthetic data?
generateTrainingData = False

# if reading data from file
#datadir = "C:/Users/admin/Desktop/research/VISMC/code/VISMC/data/fhn/[1,0]_obs_cov_0.01/"
datadir = "/Users/leah/Columbia/courses/19Spring/research/VISMC/data/fhn/[1,0]_obs_cov_0.01/"
# "C:/Users/admin/Desktop/research/VISMC/code/VISMC/data/fhn/[1,0]_obs_cov_0.01/"
# "/ifs/scratch/c2b2/ip_lab/zw2504/VISMC/data/lorenz/[1,0,0]_obs_cov_0.4/"
datadict = "datadict"
isPython2 = False

# time, n_train and n_test will be overwritten if loading data from the file
time = 200
n_train = 200 * batch_size
n_test = 40 * batch_size

# -------------------- model parameters -------------------- #
# Feed-Forward Network (FFN)
q0_layers = [32]        # q(x_1|y_1) or q(x_1|y_1:T)
q1_layers = [32]        # q(x_t|x_{t-1})
q2_layers = [32]        # q(x_t|y_t) or q(x_t|y_1:T)
f_layers = [32]
g_layers = [32]

q0_sigma_init, q0_sigma_min = 5, 1
q1_sigma_init, q1_sigma_min = 5, 1
q2_sigma_init, q2_sigma_min = 5, 1
f_sigma_init, f_sigma_min = 5, 1
g_sigma_init, g_sigma_min = 5, 1

# bidirectional RNN
y_smoother_Dhs = [32]
X0_smoother_Dhs = [32]

# ----------------------- SSM flags ------------------------ #

# if q1 and f share the same network
# (ATTENTION: even if use_2_q == True, f and q1 can still use different networks)
use_bootstrap = True

# should q use true_X to sample? (useful for debugging)
q_uses_true_X = True

# if q uses two networks q1(x_t|x_t-1) and q2(x_t|y_t)
# if True, q_uses_true_X will be overwritten as False
use_2_q = True

# whether emission uses Poisson distribution
poisson_emission = False

# ----------------------- FFN flags ------------------------ #

# if q, f and g networks also output covariance (sigma)
output_cov = False

# whether the networks only output diagonal value of cov matrix
diag_cov = False

# ----------------------- FFBSimulation flags ----------------------- #
# whether use Forward Filtering Backward Simulation
FFBSimulation = True

# When FFBSimulaitonMix is True, FFBSimulation must be True
FFBSimulationMix = True

# whether Backward Simulation sample new particles from proposal or use existing particles
BSim_sample_new_particles = True

n_particles_for_BSim_proposal = n_particles

# whether Backward Simulation proposal use unidirectional RNN or bidirectional RNN
BSim_use_single_RNN = True

# whether Forward Filtering proposal use bRNN
FF_use_bRNN = True

# --------------------- IWAE flags ---------------------- #
# whether use IWAE or SVO
IWAE = False

# --------------------- smoother flags --------------------- #
# whether smooth observations with birdectional RNNs
smooth_obs = False

# whether use a separate RNN for getting X0
X0_use_separate_RNN = True

# whether use tf.contrib.rnn.stack_bidirectional_dynamic_rnn or tf.nn.bidirectional_dynamic_rnn
# check https://stackoverflow.com/a/50552539 for differences between them
use_stack_rnn = True

# --------------------- training flags --------------------- #

# stop training early if validation set does not improve
early_stop_patience = 200

# reduce learning rate when testing loss doesn't improve for some time
lr_reduce_patience = 30

# the factor to reduce lr, new_lr = old_lr * lr_reduce_factor
lr_reduce_factor = 1 / np.sqrt(2)

# minimum lr
min_lr = lr / 10

# --------------------- printing and data saving params --------------------- #
# frequency to evaluate testing loss & other metrics and save results
print_freq = 5

# whether to save the followings during training
#   hidden trajectories
#   k-step y-hat

save_trajectory = True
save_y_hat = True

# dir to save all results
rslt_dir_name = "test_FFBS_mix"

# number of steps to predict y-hat and calculate R_square
MSE_steps = 30

# lattice shape [# of rows, # of columns] to draw arrows in quiver plot
lattice_shape = [25, 25]

# number of testing data used to save hidden trajectories, y-hat, gradient and etc
# will be clipped by number of testing data
saving_num = 30

# whether to save tensorboard
save_tensorboard = False

# whether to save model
save_model = False

q0_layers = ",".join([str(x) for x in q0_layers])
q1_layers = ",".join([str(x) for x in q1_layers])
q2_layers = ",".join([str(x) for x in q2_layers])
f_layers = ",".join([str(x) for x in f_layers])
g_layers = ",".join([str(x) for x in g_layers])
y_smoother_Dhs = ",".join([str(x) for x in y_smoother_Dhs])
X0_smoother_Dhs = ",".join([str(x) for x in X0_smoother_Dhs])
lattice_shape = ",".join([str(x) for x in lattice_shape])


# ================================================ tf.flags ================================================ #

flags = tf.app.flags


# --------------------- training hyperparameters --------------------- #

flags.DEFINE_integer("Dx", Dx, "dimension of hidden states")
flags.DEFINE_integer("Dy", Dy, "dimension of observations")

flags.DEFINE_integer("n_particles", n_particles, "number of particles")
flags.DEFINE_integer("batch_size", batch_size, "batch_size")
flags.DEFINE_float("lr", lr, "learning rate")
flags.DEFINE_integer("epoch", epoch, "number of epoch")

flags.DEFINE_integer("seed", seed, "random seed for np.random and tf")


# --------------------- data set parameters --------------------- #

flags.DEFINE_boolean("generateTrainingData", generateTrainingData, "True: generate data set from simulation; "
                                                                   "False: read data set from the file")
flags.DEFINE_string("datadir", datadir, "path of the data set file")
flags.DEFINE_string("datadict", datadict, "name of the data set file")
flags.DEFINE_boolean("isPython2", isPython2, "Was the data pickled in python 2?")


flags.DEFINE_integer("time", time, "number of timesteps for simulated data")
flags.DEFINE_integer("n_train", n_train, "number of trajactories for traning set")
flags.DEFINE_integer("n_test", n_test, "number of trajactories for testing set")


# --------------------- model parameters --------------------- #
# Feed-Forward Network (FFN) architectures
flags.DEFINE_string("q0_layers", q0_layers, "architecture for q0 network, int seperated by comma, "
                                            "for example: '50,50' ")
flags.DEFINE_string("q1_layers", q1_layers, "architecture for q1 network, int seperated by comma, "
                                            "for example: '50,50' ")
flags.DEFINE_string("q2_layers", q2_layers, "architecture for q2 network, int seperated by comma, "
                                            "for example: '50,50' ")
flags.DEFINE_string("f_layers",  f_layers,  "architecture for f network, int seperated by comma, "
                                            "for example: '50,50' ")
flags.DEFINE_string("g_layers",  g_layers,  "architecture for g network, int seperated by comma, "
                                            "for example: '50,50' ")

flags.DEFINE_float("q0_sigma_init", q0_sigma_init, "initial value of q0_sigma")
flags.DEFINE_float("q1_sigma_init", q1_sigma_init, "initial value of q1_sigma")
flags.DEFINE_float("q2_sigma_init", q2_sigma_init, "initial value of q2_sigma")
flags.DEFINE_float("f_sigma_init",  f_sigma_init,  "initial value of f_sigma")
flags.DEFINE_float("g_sigma_init",  g_sigma_init,  "initial value of g_sigma")

flags.DEFINE_float("q0_sigma_min", q0_sigma_min, "minimal value of q0_sigma")
flags.DEFINE_float("q1_sigma_min", q1_sigma_min, "minimal value of q1_sigma")
flags.DEFINE_float("q2_sigma_min", q2_sigma_min, "minimal value of q2_sigma")
flags.DEFINE_float("f_sigma_min",  f_sigma_min,  "minimal value of f_sigma")
flags.DEFINE_float("g_sigma_min",  g_sigma_min,  "minimal value of g_sigma")

# bidirectional RNN
flags.DEFINE_string("y_smoother_Dhs", y_smoother_Dhs, "number of units for y_smoother birdectional RNNs, "
                                                      "int seperated by comma")
flags.DEFINE_string("X0_smoother_Dhs", X0_smoother_Dhs, "number of units for X0_smoother birdectional RNNs, "
                                                        "int seperated by comma")

# --------------------- SSM flags --------------------- #

flags.DEFINE_boolean("use_bootstrap", use_bootstrap, "whether q1 and f share the same network, "
                                                     "(ATTENTION: even if use_2_q == True, "
                                                     "f and q1 can still use different networks)")
flags.DEFINE_boolean("q_uses_true_X", q_uses_true_X, "whether q1 uses true hidden states to sample")
flags.DEFINE_boolean("use_2_q", use_2_q, "whether q uses two networks q1(x_t|x_t-1) and q2(x_t|y_t), "
                                         "if True, q_uses_true_X will be overwritten as False")
flags.DEFINE_boolean("poisson_emission", poisson_emission, "whether emission uses Poisson distribution")

# --------------------- FFN flags --------------------- #

flags.DEFINE_boolean("output_cov", output_cov, "whether q, f and g networks also output covariance (sigma)")
flags.DEFINE_boolean("diag_cov", diag_cov, "whether the networks only output diagonal value of cov matrix")

# --------------------- FFBSimulation flags --------------------- #

flags.DEFINE_boolean("FFBSimulation", FFBSimulation, "whether use Forward Filtering Backward Simulation")
flags.DEFINE_boolean("BSim_sample_new_particles", BSim_sample_new_particles,
                     "whether Forward Filtering Backward Simulation sample new particles from proposal "
                     "or use existing particles")
flags.DEFINE_integer("n_particles_for_BSim_proposal", n_particles_for_BSim_proposal, "number of particles used for"
                                                                                     " each trajectory in "
                                                                                     "backward simulation proposal")
flags.DEFINE_boolean("BSim_use_single_RNN", BSim_use_single_RNN, "whether Backward Simulation proposal "
                                                                 "use unidirectional RNN or bidirectional RNN")
flags.DEFINE_boolean("FF_use_bRNN", FF_use_bRNN, "whether Forward Filtering proposal use bRNN")

flags.DEFINE_boolean("FFBSimulationMix", FFBSimulationMix, "whether use FFBSimulationMix")

# --------------------- IWAE flags ----------------------- #

flags.DEFINE_boolean("IWAE", IWAE, "whether use IWAE, i.e. no resampling, to train")

# --------------------- smoother flags --------------------- #

flags.DEFINE_boolean("smooth_obs", smooth_obs, "whether smooth observations with birdectional RNNs")
flags.DEFINE_boolean("X0_use_separate_RNN", X0_use_separate_RNN, "whether use a separate RNN for getting X0")
flags.DEFINE_boolean("use_stack_rnn", use_stack_rnn, "whether use tf.contrib.rnn.stack_bidirectional_dynamic_rnn "
                                                     "or tf.nn.bidirectional_dynamic_rnn")

# --------------------- training flags --------------------- #

flags.DEFINE_integer("early_stop_patience", early_stop_patience,
                     "stop training early if validation set does not improve for certain epochs")

flags.DEFINE_integer("lr_reduce_patience", lr_reduce_patience,
                     "educe learning rate when testing loss doesn't improve for some time")
flags.DEFINE_float("lr_reduce_factor", lr_reduce_factor,
                   "the factor to reduce learning rate, new_lr = old_lr * lr_reduce_factor")
flags.DEFINE_float("min_lr", min_lr, "minimum learning rate")

# --------------------- printing and data saving params --------------------- #

flags.DEFINE_integer("print_freq", print_freq, "frequency to evaluate testing loss & other metrics and save results")

flags.DEFINE_boolean("save_trajectory", save_trajectory, "whether to save hidden trajectories during training")
flags.DEFINE_boolean("save_y_hat", save_y_hat, "whether to save k-step y-hat during training")

flags.DEFINE_string("rslt_dir_name", rslt_dir_name, "dir to save all results")
flags.DEFINE_integer("MSE_steps", MSE_steps, "number of steps to predict y-hat and calculate R_square")

flags.DEFINE_string("lattice_shape", lattice_shape, "lattice shape [# of rows, # of columns] "
                                                    "to draw arrows in quiver plot")

flags.DEFINE_integer("saving_num", saving_num, "number of testing data used to "
                                               "save hidden trajectories, y-hat, gradient and etc, "
                                               "will be clipped by number of testing data")

flags.DEFINE_boolean("save_tensorboard", save_tensorboard, "whether to save tensorboard")
flags.DEFINE_boolean("save_model", save_model, "whether to save model")

FLAGS = flags.FLAGS

if __name__ == "__main__":
    tf.app.run()
