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

    def init_data_saving(self, RLT_DIR):
        self.save_res = True
        self.RLT_DIR = RLT_DIR
        self.save_trajectory = self.FLAGS.save_trajectory
        self.save_y_hat = self.FLAGS.save_y_hat
        self.saving_num = self.FLAGS.saving_num

        # metrics
        self.log_ZSMC_trains = []
        self.log_ZSMC_tests = []
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

    def init_quiver_plotting(self):
        if self.Dx == 2:
            lattice_shape = [25, 25]
            lattice_shape.append(self.Dx)
            self.lattice_shape = lattice_shape

            self.draw_quiver_during_training = True
            self.lattice = tf.placeholder(tf.float32, shape=lattice_shape, name="lattice")
            self.nextX = self.SMC.get_nextX(self.lattice)

        elif self.Dx == 3:
            self.draw_quiver_during_training = True

    def train(self,
              obs_train, obs_test,
              hidden_train, hidden_test,
              print_freq):

        self.obs_train,    self.obs_test    = obs_train,    obs_test
        self.hidden_train, self.hidden_test = hidden_train, hidden_test

        self.log_ZSMC, log = self.SMC.get_log_ZSMC(self.obs, self.hidden)

        # n_step_MSE now takes Xs as input rather than self.hidden
        # so there is no need to evalute enumerical value of Xs and feed it into self.hidden
        Xs = log["Xs"]
        y_hat_N_BxTxDy, y_N_BxTxDy = self.SMC.n_step_prediction(self.MSE_steps, Xs, self.obs)

        with tf.variable_scope("train"):
            lr = tf.placeholder(tf.float32, name="lr")
            optimizer = tf.train.AdamOptimizer(lr)
            train_op = optimizer.minimize(-self.log_ZSMC)

        init = tf.global_variables_initializer()

        # if self.model.TFS and self.model.flow_transition:
        #     from tensorflow.core.protobuf import rewriter_config_pb2
        #     config_proto = tf.ConfigProto()
        #     off = rewriter_config_pb2.RewriterConfig.OFF
        #     config_proto.graph_options.rewrite_options.memory_optimization = off
        #     self.sess = tf.Session(config=config_proto)

        self.sess = tf.Session(config=tf.ConfigProto(log_device_placement=False))

        print("initializing variables...")
        self.sess.run(init)

        # unused tensorboard stuff
        if self.save_res and self.save_tensorboard:
            self.writer.add_graph(self.sess.graph)

        for i in range(self.epoch):
            start = time.time()

            if i == 0:
                log_ZSMC_train, log_ZSMC_test, R_square_train, R_square_test = \
                    self.evaluate_and_save_metrics(i, y_hat_N_BxTxDy, y_N_BxTxDy)

            # training
            obs_train, hidden_train = shuffle(obs_train, hidden_train)
            for j in range(0, len(obs_train), self.batch_size):
                self.sess.run(train_op,
                              feed_dict={self.obs:    obs_train[j:j + self.batch_size],
                                         self.hidden: hidden_train[j:j + self.batch_size],
                                         lr:          self.lr})

            if (i + 1) % print_freq == 0:
                try:
                    log_ZSMC_train, log_ZSMC_test, R_square_train, R_square_test = \
                        self.evaluate_and_save_metrics(i, y_hat_N_BxTxDy, y_N_BxTxDy)
                    self.adjust_lr(i, print_freq)
                except StopTraining:
                    break

                if self.save_res:
                    self.saving_feed_dict = {self.obs:    obs_test[0:self.saving_num],
                                             self.hidden: hidden_test[0:self.saving_num]}

                    Xs_val = self.evaluate(Xs, self.saving_feed_dict, average=False)

                    if self.save_trajectory:
                        trajectory_dict = {"Xs": Xs_val}
                        with open(self.epoch_data_DIR + "trajectory_{}.p".format(i + 1), "wb") as f:
                            pickle.dump(trajectory_dict, f)

                    if self.save_y_hat:
                        y_hat_val = self.evaluate(y_hat_N_BxTxDy, self.saving_feed_dict, average=False)
                        y_hat_dict = {"y_hat": y_hat_val}
                        with open(self.epoch_data_DIR + "y_hat_{}.p".format(i + 1), "wb") as f:
                            pickle.dump(y_hat_dict, f)

                    if self.draw_quiver_during_training:
                        if self.Dx == 2:
                            self.draw_2D_quiver_plot(Xs_val, self.nextX, self.lattice, i + 1)
                        elif self.Dx == 3:
                            self.draw_3D_quiver_plot(Xs_val, i + 1)

            end = time.time()
            print("epoch {:<4} took {:.3f} seconds".format(i + 1, end - start))

        print("finished training...")

        metrics = {"log_ZSMC_trains": self.log_ZSMC_trains,
                   "log_ZSMC_tests":  self.log_ZSMC_tests,
                   "R_square_trains": self.R_square_trains,
                   "R_square_tests":  self.R_square_tests}
        log["y_hat"] = y_hat_N_BxTxDy

        return metrics, log

    def close_session(self):
        self.sess.close()

    def evaluate_and_save_metrics(self, iter_num, y_hat_N_BxTxDy, y_N_BxTxDy):
        log_ZSMC_train, y_hat_train, y_train = \
            self.evaluate([self.log_ZSMC, y_hat_N_BxTxDy, y_N_BxTxDy],
                          {self.obs:    self.obs_train,
                           self.hidden: self.hidden_train})
        log_ZSMC_test, y_hat_test, y_test = \
            self.evaluate([self.log_ZSMC, y_hat_N_BxTxDy, y_N_BxTxDy],
                          {self.obs:    self.obs_test,
                           self.hidden: self.hidden_test})

        log_ZSMC_train, log_ZSMC_test = np.mean(log_ZSMC_train), np.mean(log_ZSMC_test)
        R_square_train = self.evaluate_R_square(y_hat_train, y_train)
        R_square_test = self.evaluate_R_square(y_hat_test, y_test)

        print()
        print("iter", iter_num + 1)
        print("Train log_ZSMC: {:>7.3f}, valid log_ZSMC: {:>7.3f}"
              .format(log_ZSMC_train, log_ZSMC_test))

        print("Train, Valid k-step Rsq:\n", R_square_train, "\n", R_square_test)

        if not math.isfinite(log_ZSMC_train):
            print("Nan in log_ZSMC, stop training")
            raise StopTraining()

        if self.save_res:
            self.log_ZSMC_trains.append(log_ZSMC_train)
            self.log_ZSMC_tests.append(log_ZSMC_test)
            self.R_square_trains.append(R_square_train)
            self.R_square_tests.append(R_square_test)

            plot_R_square_epoch(self.RLT_DIR, R_square_train, R_square_test, iter_num + 1)

            if not os.path.exists(self.epoch_data_DIR):
                os.makedirs(self.epoch_data_DIR)
            metric_dict = {"log_ZSMC_train": log_ZSMC_train,
                           "log_ZSMC_test":  log_ZSMC_test,
                           "R_square_train": R_square_train,
                           "R_square_test":  R_square_test}
            with open(self.epoch_data_DIR + "metric_{}.p".format(iter_num + 1), "wb") as f:
                pickle.dump(metric_dict, f)

        return log_ZSMC_train, log_ZSMC_test, R_square_train, R_square_test

    def adjust_lr(self, iter_num, print_freq):
        # determine whether should decrease lr or even stop training
        if self.bestCost != np.argmax(self.log_ZSMC_tests):
            self.early_stop_count = 0
            self.lr_reduce_count = 0
            self.bestCost = np.argmax(self.log_ZSMC_tests)

        print("best valid cost on iter: {}\n".format(self.bestCost * print_freq))

        if self.bestCost != len(self.log_ZSMC_tests) - 1:
            self.early_stop_count += 1
            if self.early_stop_count * print_freq == self.early_stop_patience:
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
                elif isinstance(fetches_list[0][i], list):
                    tmp = [np.concatenate([x[i][j] for x in fetches_list]) for j in range(len(fetches_list[0][i]))]
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

    def evaluate_R_square(self, y_hat, y):
        n_steps = len(y_hat) - 1

        def get_R_square(y_hat_i, y_i):
            MSE = np.sum((y_hat_i - y_i) ** 2)
            y_i_mean = np.mean(y_i, axis=0, keepdims=True)
            y_i_var = np.sum((y_i - y_i_mean) ** 2)
            return 1 - MSE / y_i_var

        R_square = np.zeros(n_steps + 1)
        for i, (y_hat_i, y_i) in enumerate(zip(y_hat, y)):
            R_square[i] = get_R_square(y_hat_i, y_i)

        return R_square

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

            nextX = self.sess.run(nextX, feed_dict={lattice: lattice_val})

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
