import numpy as np
from sklearn.utils import shuffle
import math

import tensorflow as tf
import os
import pickle
import time
import pdb

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from rslts_saving.rslts_saving import plot_R_square_epoch

SAVE_COUNT_DOWN = 1


class StopTraining(Exception):
    pass


class trainer:
    def __init__(self, model, SMC, FLAGS):
        self.model = model
        self.SMC = SMC
        self.FLAGS = FLAGS

        self.Dx = self.FLAGS.Dx
        self.Dy = self.FLAGS.Dy
        self.time = self.FLAGS.time
        self.n_particles = self.FLAGS.n_particles

        self.MSE_steps = self.FLAGS.MSE_steps

        self.save_res = False
        self.draw_quiver_during_training = False

        self.init_placeholder()
        self.init_training_param()
        self.init_quiver_plotting()

    def init_placeholder(self):
        self.obs = self.model.obs
        self.hidden = self.model.hidden
        self.Input = self.model.Input
        self.dropout = self.model.dropout
        self.smoothing_perc = self.model.smoothing_perc

    def init_training_param(self):
        self.batch_size = self.FLAGS.batch_size
        self.lr = self.FLAGS.lr
        self.epoch = self.FLAGS.epoch

        # early stopping
        self.early_stop_patience = self.FLAGS.early_stop_patience
        self.bestCost = 0
        self.early_stop_count = 0

        # lr auto decreasing
        self.lr_reduce_factor = self.FLAGS.lr_reduce_factor
        self.lr_reduce_patience = self.FLAGS.lr_reduce_patience
        self.min_lr = self.FLAGS.min_lr
        self.lr_reduce_count = 0

        # global gradient norm clip
        self.clip_norm = self.FLAGS.clip_norm

        self.dropout_rate = self.FLAGS.dropout_rate

        # FFBS
        self.smoothing_perc_factor = self.FLAGS.smoothing_perc_factor

    def init_data_saving(self, RLT_DIR):
        self.save_res = True
        self.RLT_DIR = RLT_DIR
        self.save_trajectory = self.FLAGS.save_trajectory
        self.save_y_hat = self.FLAGS.save_y_hat
        self.saving_num = self.FLAGS.saving_num

        # metrics
        self.log_ZSMC_trains = []
        self.log_ZSMC_tests = []
        self.MSE_trains = []
        self.MSE_tests = []
        self.R_square_trains = []
        self.R_square_tests = []

        # epoch data (trajectory, y_hat and quiver lattice)
        epoch_data_DIR = self.RLT_DIR.split("/")
        epoch_data_DIR.insert(epoch_data_DIR.index("rslts") + 1, "epoch_data")
        self.epoch_data_DIR = "/".join(epoch_data_DIR)

        # tensorboard and model saver
        self.save_tensorboard = self.FLAGS.save_tensorboard
        self.save_model = self.FLAGS.save_model
        if self.save_tensorboard:
            self.writer = tf.summary.FileWriter(self.RLT_DIR)
        if self.save_model:
            self.saver = tf.train.Saver(max_to_keep=1)

        # collect gradients to calculate SNR
        self.save_gradient = self.FLAGS.save_gradient
        if self.save_gradient:
            self.SNR_sample_num = self.FLAGS.SNR_sample_num

            self.SNR_NP_list = [int(x) for x in self.FLAGS.SNR_NP_list.split(",")]

            self.SNR_collect_grads_points = [int(x) for x in self.FLAGS.SNR_collect_grads_points.split(",")]

            flag = [False for i in range(len(self.SNR_collect_grads_points))]
            self.SNR_collect_grads_flag = dict(zip(self.SNR_collect_grads_points, flag))
            self.save_count_down = -1

        epoch_data_DIR = self.RLT_DIR.split("/")
        epoch_data_DIR.insert(epoch_data_DIR.index("rslts") + 1, "epoch_data")
        self.epoch_data_DIR = "/".join(epoch_data_DIR)



    def init_quiver_plotting(self):
        if self.Dx == 2:
            lattice_shape = [int(x) for x in self.FLAGS.lattice_shape.split(",")]
            assert len(lattice_shape) == self.Dx
            lattice_shape.append(self.Dx)
            self.lattice_shape = lattice_shape

            self.draw_quiver_during_training = True
            self.lattice = tf.placeholder(tf.float32, shape=lattice_shape, name="lattice")
            self.nextX = self.SMC.get_nextX(self.lattice)

        elif self.Dx == 3:
            self.draw_quiver_during_training = True

    def get_variables(self):
        trans_variables_dict = {}

        # K = 1
        SMC = self.SMC

        q0 = SMC.q0.transformation
        q1 = SMC.q1.transformation
        g = SMC.g.transformation
        q2 = None if self.SMC.q2 is None else SMC.q2.transformation  # If not using 2q network, q2 == None
        f = None if self.SMC.f == self.SMC.q1 else SMC.f.transformation  # If using bootstrap, f == q1

        for MLP_trans in [q0, q1, q2, f, g]:
            if MLP_trans is None:
                continue

            variables_dict = MLP_trans.get_variables()
            for key, val in variables_dict.items():
                trans_variables_dict[MLP_trans.name + "/" + key] = val

        variable_names = list(trans_variables_dict.keys())
        variables = list(trans_variables_dict.values())

        return variable_names, variables


    def set_up_gradient(self, list_of_loss):
        variable_names, variables = self.get_variables()

        list_of_gradients_dict = []
        for loss in list_of_loss:
            gradients = tf.gradients(loss, variables)
            gradients_dict = dict(zip(variable_names, gradients))
            list_of_gradients_dict.append(gradients_dict)

        return list_of_gradients_dict

    def evaluate_gradients(self, gradients_dict, feed_dict):
        variable_names = list(gradients_dict.keys())
        gradients = list(gradients_dict.values())
        gradients_val_samples = [self.evaluate(gradients, feed_dict, average=True) for _ in range(self.SNR_sample_num)]
        gradients_val = [np.stack([gradients_val_sample[i] for gradients_val_sample in gradients_val_samples])
                         for i in range(len(gradients))]
        res_dict = dict(zip(variable_names, gradients_val))

        return res_dict

    def train(self,
              obs_train, obs_test,
              hidden_train, hidden_test,
              input_train, input_test,
              print_freq, loss_type):

        self.obs_train,    self.obs_test    = obs_train,    obs_test
        self.hidden_train, self.hidden_test = hidden_train, hidden_test
        self.input_train,  self.input_test  = input_train,  input_test

        original_loss_type = loss_type
        if loss_type == 'resampling':
            loss_type = 'full'

        self.log_ZSMC, log, resampling_loss = self.SMC.get_log_ZSMC(self.obs, self.hidden, self.Input,
                                                                    loss_type=loss_type, n_particles=self.SNR_NP_list[0])
        print("build log_ZSMC for n_particles = ", self.SNR_NP_list[0])

        if loss_type == 'full':
            self.loss = self.log_ZSMC + resampling_loss
        else:
            self.loss = self.log_ZSMC

        list_of_loss_np = [self.loss]
        if self.save_gradient:
            if len(self.SNR_NP_list) > 1:
                for n_particles in self.SNR_NP_list[1:]:
                    print("build log_ZSMC for n_particles = ", n_particles)
                    log_ZSMC_np, log, resampling_loss_np = \
                        self.SMC.get_log_ZSMC(self.obs, self.hidden, self.Input,
                                              loss_type=loss_type, n_particles=n_particles)
                    if original_loss_type == 'full':
                        loss_np = log_ZSMC_np + resampling_loss_np
                    elif original_loss_type == 'resampling':
                        loss_np = resampling_loss_np
                    else:
                        # original_loss_type = 'main', or 'soft'
                        loss_np = log_ZSMC_np

                    list_of_loss_np.append(loss_np)

            self.list_of_gradients_dict = self.set_up_gradient(list_of_loss_np)


        # n_step_MSE now takes Xs as input rather than self.hidden
        # so there is no need to evalute enumerical value of Xs and feed it into self.hidden
        Xs = log["Xs"]
        #MSE_ks, y_means, y_vars, y_hat = self.SMC.n_step_MSE(self.MSE_steps, Xs, self.obs, self.Input)

        with tf.variable_scope("train"):
            lr = tf.placeholder(tf.float32, name="lr")
            optimizer = tf.train.AdamOptimizer(lr)
            train_op = optimizer.minimize(-self.loss)
            # gradients, variables = zip(*optimizer.compute_gradients(-self.log_ZSMC))
            # gradients, _ = tf.clip_by_global_norm(gradients, self.clip_norm)
            # train_op = optimizer.apply_gradients(zip(gradients, variables))

        init = tf.global_variables_initializer()

        self.sess = tf.Session()

        print("initializing variables...")
        self.sess.run(init)
        print("start training...")

        # unused tensorboard stuff
        if self.save_res and self.save_tensorboard:
            self.writer.add_graph(self.sess.graph)

        for i in range(self.epoch):
            start = time.time()

            # FFBS interpolation
            if i < self.epoch * 3 / 4:
                smoothing_perc_epoch = 1 - (1 - i / self.epoch) ** self.smoothing_perc_factor
            else:
                smoothing_perc_epoch = 1

            if i == 0:
                log_ZSMC_train, log_ZSMC_test = \
                    self.evaluate_and_save_metrics(i, smoothing_perc_epoch)
                    #self.evaluate_and_save_metrics(i, MSE_ks, y_means, y_vars, smoothing_perc_epoch)

            # training
            obs_train, hidden_train = shuffle(obs_train, hidden_train)
            #print("running train_op...")
            for j in range(0, len(obs_train), self.batch_size):
                self.sess.run(train_op,
                              feed_dict={self.obs:            obs_train[j:j + self.batch_size],
                                         self.hidden:         hidden_train[j:j + self.batch_size],
                                         self.Input:          input_train[j:j + self.batch_size],
                                         self.dropout:        np.ones(self.batch_size) * self.dropout_rate,
                                         self.smoothing_perc: np.ones(self.batch_size) * smoothing_perc_epoch,
                                         lr:                  self.lr})

            #print("start evaluating metrics...")
            if (i + 1) % print_freq == 0:
                try:
                    #print("start evaluating log_ZSMC")
                    log_ZSMC_train, log_ZSMC_test = \
                        self.evaluate_and_save_metrics(i, smoothing_perc_epoch)
                        #self.evaluate_and_save_metrics(i, MSE_ks, y_means, y_vars, smoothing_perc_epoch)
                    self.adjust_lr(i, print_freq)
                except StopTraining:
                    break

                if self.save_res:
                    self.saving_feed_dict = {self.obs:            obs_test[0:self.saving_num],
                                             self.hidden:         hidden_test[0:self.saving_num],
                                             self.Input:          input_test[0:self.saving_num],
                                             self.dropout:        np.zeros(self.saving_num),
                                             self.smoothing_perc: np.ones(self.saving_num)}

                    Xs_val = self.evaluate(Xs, self.saving_feed_dict, average=False)

                    if self.save_trajectory:
                        trajectory_dict = {"Xs": Xs_val}
                        with open(self.epoch_data_DIR + "trajectory_{}.p".format(i + 1), "wb") as f:
                            pickle.dump(trajectory_dict, f)
                    """
                    if self.save_y_hat:
                        y_hat_val = self.evaluate(y_hat, self.saving_feed_dict, average=False)
                        y_hat_dict = {"y_hat": y_hat_val}
                        with open(self.epoch_data_DIR + "y_hat_{}.p".format(i + 1), "wb") as f:
                            pickle.dump(y_hat_dict, f)
                    """

                    if self.draw_quiver_during_training:
                        if self.Dx == 2:
                            self.draw_2D_quiver_plot(Xs_val, self.nextX, self.lattice, i + 1)
                        elif self.Dx == 3:
                            self.draw_3D_quiver_plot(Xs_val, i + 1)

                    #---------------- save gradients ---------------------#
                    if self.save_gradient:

                        for check_point in self.SNR_collect_grads_points:
                            if not self.SNR_collect_grads_flag[check_point] and log_ZSMC_train > check_point:
                                print("Surpassing {}, collecting the gradients....\n".format(check_point))
                                self.SNR_collect_grads_flag[check_point] = True
                                self.save_count_down = SAVE_COUNT_DOWN
                                break

                        if self.save_count_down > 0:
                            self.save_count_down -= 1
                            print("Count down: ", self.save_count_down)
                            gradients_feed_dict = {self.obs: obs_train[0:self.saving_num],
                                                   self.hidden: hidden_train[0:self.saving_num],
                                                   self.Input: input_train[0:self.saving_num],
                                                   self.dropout: np.zeros(self.saving_num),
                                                   self.smoothing_perc: np.ones(self.saving_num) * smoothing_perc_epoch}

                            np_idx = 0
                            for gradients_dict in self.list_of_gradients_dict:
                                if np_idx == 0:
                                    np_idx += 1
                                    continue
                                gradients_val_dict = \
                                    self.evaluate_gradients(gradients_dict, gradients_feed_dict)

                                n_particles = self.SNR_NP_list[np_idx]
                                with open(
                                        self.epoch_data_DIR + "gradient_{}_np_{}.p".format(i + 1, n_particles),
                                        "wb") as f:
                                    print("Dump gradients for epoch {} np {}".format(i + 1, n_particles))
                                    pickle.dump(gradients_val_dict, f)

                                np_idx += 1

                            # ----------------------- end of saving gradients --------------------#

            end = time.time()
            print("epoch {:<4} took {:.3f} seconds".format(i + 1, end - start))

        print("finished training...")

        metrics = {"log_ZSMC_trains": self.log_ZSMC_trains,
                   "log_ZSMC_tests":  self.log_ZSMC_tests,
                   "MSE_trains":      self.MSE_trains,
                   "MSE_tests":       self.MSE_tests,
                   "R_square_trains": self.R_square_trains,
                   "R_square_tests":  self.R_square_tests}
        #log["y_hat"] = y_hat

        return metrics, log

    def close_session(self):
        self.sess.close()

    #def evaluate_and_save_metrics(self, iter_num, MSE_ks, y_means, y_vars, smoothing_perc_epoch):
    def evaluate_and_save_metrics(self, iter_num, smoothing_perc_epoch):
        #print("evaluate and save metrics", iter_num)
        #print("n_particles = ", self.SMC.n_particles)

        #print("evaluate log_ZSMC_train")
        log_ZSMC_train = self.evaluate(self.log_ZSMC,
                                       {self.obs:            self.obs_train,
                                        self.hidden:         self.hidden_train,
                                        self.Input:          self.input_train,
                                        self.dropout:        np.zeros(len(self.obs_train)),
                                        self.smoothing_perc: np.ones(len(self.obs_train)) * smoothing_perc_epoch},
                                       average=True)

        #print("evaluate log_ZSMC_test")
        log_ZSMC_test = self.evaluate(self.log_ZSMC,
                                      {self.obs:            self.obs_test,
                                       self.hidden:         self.hidden_test,
                                       self.Input:          self.input_test,
                                       self.dropout:        np.zeros(len(self.obs_test)),
                                       self.smoothing_perc: np.ones(len(self.obs_test)) * smoothing_perc_epoch},
                                      average=True)
        """
        print("evaluate MSE_train, R_square_train")
        MSE_train, R_square_train = self.evaluate_R_square(MSE_ks, y_means, y_vars,
                                                           self.hidden_train, self.obs_train, self.input_train)
        print("evaluate MSE_test, R_square_test")
        MSE_test, R_square_test = self.evaluate_R_square(MSE_ks, y_means, y_vars,
                                                         self.hidden_test, self.obs_test, self.input_test)
        """

        print("iter", iter_num + 1)
        print("Train log_ZSMC: {:>7.3f}, valid log_ZSMC: {:>7.3f}"
              .format(log_ZSMC_train, log_ZSMC_test))

        #print("Train, Valid k-step Rsq:\n", R_square_train, "\n", R_square_test)

        if not math.isfinite(log_ZSMC_train):
            print("Nan in log_ZSMC, stop training")
            raise StopTraining()

        if self.save_res:
            self.log_ZSMC_trains.append(log_ZSMC_train)
            self.log_ZSMC_tests.append(log_ZSMC_test)
            #self.MSE_trains.append(MSE_train)
            #self.MSE_tests.append(MSE_test)
            #self.R_square_trains.append(R_square_train)
            #self.R_square_tests.append(R_square_test)

            #plot_R_square_epoch(self.RLT_DIR, R_square_train, R_square_test, iter_num + 1)

            if not os.path.exists(self.epoch_data_DIR):
                os.makedirs(self.epoch_data_DIR)
            metric_dict = {"log_ZSMC_train": log_ZSMC_train,
                           "log_ZSMC_test":  log_ZSMC_test}
                           #"R_square_train": R_square_train,
                           #"R_square_test":  R_square_test}
            with open(self.epoch_data_DIR + "metric_{}.p".format(iter_num + 1), "wb") as f:
                pickle.dump(metric_dict, f)

        #return log_ZSMC_train, log_ZSMC_test, R_square_train, R_square_test
        return log_ZSMC_train, log_ZSMC_test

    def adjust_lr(self, iter_num, print_freq):
        # determine whether should decrease lr or even stop training
        if self.bestCost != np.argmax(self.log_ZSMC_tests):
            self.early_stop_count = 0
            self.lr_reduce_count = 0
            self.bestCost = np.argmax(self.log_ZSMC_tests)

        print("best valid cost on iter: {}\n".format(self.bestCost * print_freq))

        if self.bestCost != len(self.log_ZSMC_tests) - 1:
            self.early_stop_count += 1
            if self.early_stop_count == self.early_stop_patience:
                print("valid cost not improving. stopping training...")
                raise StopTraining()

            self.lr_reduce_count += 1
            if self.lr_reduce_count * print_freq == self.lr_reduce_patience:
                self.lr_reduce_count = 0
                self.lr = max(self.lr * self.lr_reduce_factor, self.min_lr)
                print("valid cost not improving. reduce learning rate to {}".format(self.lr))

        if self.save_model:
            if not os.path.exists(self.RLT_DIR + "model/"):
                os.makedirs(self.RLT_DIR + "model/")
            if self.bestCost == len(self.log_ZSMC_tests) - 1:
                print("Test log_ZSMC improves to {}, save model".format(self.log_ZSMC_tests[-1]))
                self.saver.save(self.sess, self.RLT_DIR + "model/model_epoch", global_step=iter_num + 1)

    def evaluate(self, fetches, feed_dict_w_batches={}, average=False, keepdims=False):
        """
        Evaluate fetches across multiple batches of feed_dict
        fetches: a single tensor or list of tensor to evaluate
        feed_dict_w_batches: {placeholder: input of multiple batches}
        average: whether to average fetched values across batches
        keepdims: if not averaging across batches, for N-d tensor in feteches, whether to keep
            the dimension for different batches.
        """
        if not feed_dict_w_batches:
            return self.sess.run(fetches)

        n_batches = len(list(feed_dict_w_batches.values())[0])
        assert n_batches >= self.batch_size

        fetches_list = []
        feed_dict = {}
        for i in range(0, n_batches, self.batch_size):
            for key, value in feed_dict_w_batches.items():
                feed_dict[key] = value[i:i + self.batch_size]
            fetches_val = self.sess.run(fetches, feed_dict=feed_dict)
            fetches_list.append(fetches_val)

        res = []
        if isinstance(fetches, list):
            for i in range(len(fetches)):
                if isinstance(fetches_list[0][i], np.ndarray):
                    if keepdims:
                        tmp = np.stack([x[i] for x in fetches_list])
                    else:
                        tmp = np.concatenate([x[i] for x in fetches_list])
                else:
                    tmp = np.array([x[i] for x in fetches_list])
                res.append(tmp)
        else:
            if isinstance(fetches_list[0], np.ndarray):
                res = np.stack(fetches_list) if keepdims else np.concatenate(fetches_list)
            else:
                res = np.array(fetches_list)

        if average:
            if isinstance(res, list):
                res = [np.mean(x, axis=0) for x in res]
            else:
                res = np.mean(res, axis=0)

        return res

    def evaluate_R_square(self, MSE_ks, y_means, y_vars, hidden_set, obs_set, input_set):
        n_steps = y_means.shape.as_list()[0] - 1
        Dy = y_means.shape.as_list()[1]
        batch_size = self.batch_size
        n_batches = hidden_set.shape[0]

        combined_MSE_ks = np.zeros((n_steps + 1))             # combined MSE_ks across all batches
        combined_y_means = np.zeros((n_steps + 1, Dy))        # combined y_means across all batches
        combined_y_vars = np.zeros((n_steps + 1, Dy))         # combined y_vars across all batches

        print("evaluate_R_Square")
        for i in range(0, n_batches, batch_size):
            print("batch ", i)
            batch_MSE_ks, batch_y_means, batch_y_vars = self.sess.run([MSE_ks, y_means, y_vars],
                                                                      {self.obs: obs_set[i:i + batch_size],
                                                                       self.hidden: hidden_set[i:i + batch_size],
                                                                       self.Input: input_set[i:i + batch_size],
                                                                       self.dropout: np.zeros(batch_size),
                                                                       self.smoothing_perc: np.ones(batch_size)})
            # batch_MSE_ks.shape = (n_steps + 1)
            # batch_y_means.shape = (n_steps + 1, Dy)
            # batch_y_vars.shape = (n_steps + 1, Dy)

            # update combined_MSE_ks just by summing them across all batches
            combined_MSE_ks += batch_MSE_ks

            # update combined y_means and combined y_vars according to:
            # https://stats.stackexchange.com/questions/55999/is-it-possible-to-find-the-combined-standard-deviation
            Tmks = np.arange(self.time - n_steps, self.time + 1, 1)  # [time - n_steps, time - n_steps + 1, ..., time]
            Tmks = Tmks[-1:None:-1]                                  # [time, ..., time - n_steps + 1, time - n_steps]
            TmkxDy = np.tile(Tmks, (Dy, 1)).T                        # (n_steps + 1, Dy)

            # for k = 0, ..., n_steps,
            # its n1 = (time - k) * i, n2 = (time - k) * batch_size respectively
            n1 = TmkxDy * i                                     # (n_steps + 1, Dy)
            n2 = TmkxDy * batch_size                            # (n_steps + 1, Dy)

            combined_y_means_new = (n1 * combined_y_means + n2 * batch_y_means) / (n1 + n2)
            combined_y_vars = combined_y_vars + batch_y_vars + \
                n1 * (combined_y_means - combined_y_means_new)**2 + \
                n2 * (batch_y_means - combined_y_means_new)**2

            combined_y_means = combined_y_means_new

        combined_y_vars = np.mean(combined_y_vars, axis=1)
        R_square = 1 - combined_MSE_ks / combined_y_vars
        mean_MSE_ks = combined_MSE_ks / (Tmks * n_batches)

        return mean_MSE_ks, R_square

    def draw_2D_quiver_plot(self, Xs_val, nextX, lattice, epoch):
        # Xs_val.shape = (saving_num, time, n_particles, Dx)
        X_trajs = np.mean(Xs_val, axis=2)

        plt.figure()
        for X_traj in X_trajs[0:self.saving_num]:
            plt.plot(X_traj[:, 0], X_traj[:, 1])
            plt.scatter(X_traj[0, 0], X_traj[0, 1])
        plt.title("quiver")
        plt.xlabel("x_dim 1")
        plt.ylabel("x_dim 2")

        if nextX is not None:
            axes = plt.gca()
            x1range, x2range = axes.get_xlim(), axes.get_ylim()
            X = lattice_val = self.define2Dlattice(x1range, x2range)

            nextX = self.sess.run(nextX, feed_dict={lattice: lattice_val,
                                                    self.dropout: 0})

            scale = int(5 / 3 * max(abs(x1range[0]) + abs(x1range[1]), abs(x2range[0]) + abs(x2range[1])))
            plt.quiver(X[:, :, 0], X[:, :, 1], nextX[:, :, 0] - X[:, :, 0], nextX[:, :, 1] - X[:, :, 1], scale=scale)

            quiver_dict = {"X_trajs": X_trajs, "X": X, "nextX": nextX}
            with open(self.epoch_data_DIR + "lattice_val_{}.p".format(epoch), "wb") as f:
                pickle.dump(quiver_dict, f)

        # sns.despine()
        if not os.path.exists(self.RLT_DIR + "quiver/"):
            os.makedirs(self.RLT_DIR + "quiver/")
        plt.savefig(self.RLT_DIR + "quiver/epoch_{}".format(epoch))
        plt.close()

    def define2Dlattice(self, x1range=(-30.0, 30.0), x2range=(-30.0, 30.)):

        x1coords = np.linspace(x1range[0], x1range[1], num=self.lattice_shape[0])
        x2coords = np.linspace(x2range[0], x2range[1], num=self.lattice_shape[1])
        Xlattice = np.stack(np.meshgrid(x1coords, x2coords), axis=-1)
        return Xlattice

    def draw_3D_quiver_plot(self, Xs_val, epoch):
        # Xs_val.shape = (saving_num, time, n_particles, Dx)
        X_trajs = np.mean(Xs_val, axis=2)

        fig = plt.figure()
        ax = fig.gca(projection="3d")
        plt.title("hidden state for all particles")
        ax.set_xlabel("x_dim 1")
        ax.set_ylabel("x_dim 2")
        ax.set_zlabel("x_dim 3")
        for X_traj in X_trajs:
            ax.plot(X_traj[:, 0], X_traj[:, 1], X_traj[:, 2])
            ax.scatter(X_traj[0, 0], X_traj[0, 1], X_traj[0, 2])

        if not os.path.exists(self.RLT_DIR + "quiver/"):
            os.makedirs(self.RLT_DIR + "quiver/")
        for angle in range(45, 360, 45):
            ax.view_init(30, angle)
            plt.savefig(self.RLT_DIR + "quiver/epoch_{}_angle_{}".format(epoch, angle))
        plt.close()