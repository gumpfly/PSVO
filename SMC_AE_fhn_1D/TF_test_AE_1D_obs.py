import numpy as np
import math
from sklearn.utils import shuffle

import tensorflow as tf
import pdb

# import from files
from Encoder import Encoder
from Encoder_two_obs import Encoder_two_obs
from Encoder_full_obs import Encoder_full_obs
from fhn_sampler import create_train_test_dataset
from distributions import mvn, poisson, tf_mvn, tf_poisson
from fhn_transition import tf_fhn
from SMC import SMC
from rslts_saving import create_RLT_DIR, NumpyEncoder, plot_training_data, plot_learning_results, plot_2D_results, plot_losses

# for data saving stuff
import sys
import pickle
import json
import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' # to reduce a lot of log about the device


print("Akwaaba!")
print(tf.__version__)

if __name__ == '__main__':

	# ============================== hyperparameters ============================== #

	Dy, Dx = 1, 2
	n_particles = 1000
	time = 200

	batch_size = 5
	lr = 2e-3
	epoch = 300
	seed = 0

	n_train = 200 	* batch_size
	n_test  = 1		* batch_size

	print_freq = 10
	save_freq = 10
	store_res = True
	max_fig_num = 20
	encoder_architecture = "Encoder_full_obs" # "Encoder_two_obs" or "Encoder_full_obs" or "Encoder"
	rslt_dir_name = 'AutoEncoder_1D_obs'

	tf.set_random_seed(seed)
	np.random.seed(seed)

	# ============================== model parameters ============================== #

	# transition
	mya, myb, myc = 1.0, 0.95, 0.05
	I = 1.0
	dt = 0.15
	Q_true = np.asarray([[1., 0], [0, 1.]])
	# emission
	B_true = np.asarray([[1., 0]])
	Sigma_true = np.diag([0.15])
	# initial state
	# x_0_true = np.array([1.0, 1.0])

	B_init 			= B_true
	L_Q_init 		= np.linalg.cholesky(Q_true)
	L_Sigma_init 	= np.linalg.cholesky(Sigma_true)
	# x_0_init = x_0_true

	# create dir to store results
	if store_res == True:
		Experiment_params = {"n_particles":n_particles, "time":time, "batch_size":batch_size,
							 "lr":lr, "epoch":epoch, "seed":seed, "n_train":n_train,
							 "encoder_architecture":encoder_architecture,
							 "rslt_dir_name":rslt_dir_name}
		print('Experiment_params')
		for key, val in Experiment_params.items():
			print('\t{}:{}'.format(key, val))
		RLT_DIR = create_RLT_DIR(Experiment_params)
		print("RLT_DIR:", RLT_DIR)

	# Create train and test dataset
	fhn_params = (mya, myb, myc, I)
	g = mvn(B_true, Sigma_true)
	t = np.arange(0.0, time*dt, dt)
	hidden_train, obs_train, hidden_test, obs_test = create_train_test_dataset(n_train, n_test, fhn_params, g, t)
	print("finish creating dataset")

	# ================================ TF stuffs starts ================================ #

	# placeholders
	obs = tf.placeholder(tf.float32, shape=(batch_size, time, Dy), name = 'obs')
	x_0 = tf.placeholder(tf.float32, shape=(batch_size, Dx), name = 'x_0')

	if encoder_architecture == "Encoder_two_obs":
		encoder_cell = Encoder_two_obs(Dx, Dy, n_particles, batch_size, time)
	elif encoder_architecture == "Encoder_full_obs":
		encoder_cell = Encoder_full_obs(Dx, Dy, n_particles, batch_size, time)
	else:
		encoder_cell = Encoder(Dx, n_particles, batch_size, time)

	# for evaluating true log_ZSMC
	# transition
	Q_true_tnsr 	= tf.Variable(Q_true, 		dtype=tf.float32, trainable = False, name='Q_true')
	# emission
	B_true_tnsr 	= tf.Variable(B_true, 		dtype=tf.float32, trainable = False, name='B_true')
	Sigma_true_tnsr = tf.Variable(Sigma_true, 	dtype=tf.float32, trainable = False, name='Q_true')
	fhn_params = (mya, myb, myc, I, dt)
	q_true = tf_mvn(n_particles, batch_size, tf.eye(Dx),  (1**2)*tf.eye(Dx), None, name = 'q_true')
	f_true = tf_fhn(n_particles, batch_size, fhn_params,  Q_true_tnsr, 		 x_0,  name = 'f_true')
	g_true = tf_mvn(n_particles, batch_size, B_true_tnsr, Sigma_true_tnsr,	 None, name = 'g_true')

	# for training
	# transition
	L_Q 	= tf.Variable(L_Q_init, 	dtype=tf.float32, trainable = False, name='L_Q')
	Q 		= tf.matmul(L_Q, 	 L_Q, 	  transpose_b = True, name = 'Q')
	# emission
	B 		= tf.Variable(B_init, 		dtype=tf.float32, trainable = False, name='B')
	L_Sigma = tf.Variable(L_Sigma_init, dtype=tf.float32, trainable = False, name='L_Sigma')
	Sigma 	= tf.matmul(L_Sigma, L_Sigma, transpose_b = True, name = 'Sigma')

	q_train = tf_mvn(n_particles, batch_size, tf.eye(Dx), (1**2)*tf.eye(Dx), None,  name = 'q_train')
	g_train = tf_mvn(n_particles, batch_size, B, 		  Sigma, 			  None, name = 'g_train')

	# for train_op
	SMC_true  = SMC(q_true,  f_true, g_true,  n_particles, batch_size, name = 'log_ZSMC_true')
	# f_true is passed in to calculate f_nu_log_probs at t = 0, not used for t = 1, 2, ...
	SMC_train = SMC(q_train, f_true, g_train, n_particles, batch_size, encoder_cell = encoder_cell, name = 'log_ZSMC_train')
	log_ZSMC_true,  log_true  = SMC_true.get_log_ZSMC(obs)
	log_ZSMC_train, log_train = SMC_train.get_log_ZSMC(obs)
	
	with tf.name_scope('train'):
		train_op = tf.train.AdamOptimizer(lr).minimize(-log_ZSMC_train)
	
	if store_res == True:
		writer = tf.summary.FileWriter(RLT_DIR)
		saver = tf.train.Saver()

	# check trainable variables
	# print('trainable variables:')
	# for var in tf.trainable_variables():
	# 	print(var)

	init = tf.global_variables_initializer()

	# for plot
	log_ZSMC_trains = []
	log_ZSMC_tests = []
	with tf.Session() as sess:

		sess.run(init)

		if store_res == True:
			writer.add_graph(sess.graph)

		log_ZSMC_true_val = SMC_true.tf_accuracy(sess, log_ZSMC_true, obs, obs_train+obs_test, x_0, hidden_train+hidden_test)
		log_ZSMC_train_val = SMC_train.tf_accuracy(sess, log_ZSMC_train, obs, obs_train, x_0, hidden_train)
		log_ZSMC_test_val  = SMC_train.tf_accuracy(sess, log_ZSMC_train, obs, obs_test,  x_0, hidden_test)
		print("log_ZSMC_true_val: {:<7.3f}".format(log_ZSMC_true_val))
		print("iter {:>3}, train log_ZSMC: {:>7.3f}, test log_ZSMC: {:>7.3f}"\
			.format(0, log_ZSMC_train_val, log_ZSMC_test_val))

		log_ZSMC_trains.append(log_ZSMC_train_val)
		log_ZSMC_tests.append(log_ZSMC_test_val)

		for i in range(epoch):
			# train A, B, Q, x_0 using each training sample
			obs_train, hidden_train = shuffle(obs_train, hidden_train)
			for j in range(0, len(obs_train), batch_size):
				# print("encoder_cell.sigma")
				# print(encoder_cell.sigma.eval())
				sess.run(train_op, feed_dict={obs:obs_train[j:j+batch_size], 
											  x_0:[hidden[0] for hidden in hidden_train[j:j+batch_size]]})
				
			# print training and testing loss
			if (i+1)%print_freq == 0:
				log_ZSMC_train_val = SMC_train.tf_accuracy(sess, log_ZSMC_train, obs, obs_train, x_0, hidden_train)
				log_ZSMC_test_val  = SMC_train.tf_accuracy(sess, log_ZSMC_train, obs, obs_test,  x_0, hidden_test)
				print("iter {:>3}, train log_ZSMC: {:>7.3f}, test log_ZSMC: {:>7.3f}"\
					.format(i+1, log_ZSMC_train_val, log_ZSMC_test_val))

				log_ZSMC_trains.append(log_ZSMC_train_val)
				log_ZSMC_tests.append(log_ZSMC_test_val)

			if store_res == True and (i+1)%save_freq == 0:
				saver.save(sess, os.path.join(RLT_DIR, 'model/model_epoch'), global_step=i+1)

		Q_learned = Q.eval()
		B_learned = B.eval()
		Sigma_learned = Sigma.eval()

		Xs = log_train[0]
		As = log_train[-1]
		Xs_val = np.zeros((n_train, time, n_particles, Dx))
		As_val = np.zeros((n_train, time-1, Dx, Dx))
		for i in range(0, min(len(hidden_train), max_fig_num), batch_size):
			X_val, A_val = sess.run([Xs, As], 
									  feed_dict = {obs:obs_train[i:i+batch_size],
									  			   x_0:[hidden[0] for hidden in hidden_train[i:i+batch_size]]})
			for j in range(batch_size):
				Xs_val[i+j] = X_val[:, :, j, :]
				As_val[i+j] = A_val[j]

	sess.close()

	print("finish training")

	if store_res == True:
		plot_training_data(RLT_DIR, hidden_train, obs_train, max_fig_num = max_fig_num)
		plot_learning_results(RLT_DIR, Xs_val, hidden_train, max_fig_num = max_fig_num)
		plot_2D_results(RLT_DIR, As_val, hidden_train)

		hyperparams_dict = {"T":time, "n_particles":n_particles, "batch_size":batch_size, "lr":lr,
				 			"epoch":epoch, "n_train":n_train, "seed":seed,
				 			"encoder_architecture":encoder_architecture}
		modelparams_dict = {"mya":mya, "myb":myb, "myc":myc, "I":I, "dt":dt}
		training_data_dict = {"hidden_train":hidden_train[:max_fig_num]}
		true_model_dict = { "Q_true":Q_true, 
							"B_true":B_true, "Sigma_true":Sigma_true}
		init_model_dict = { "Q_init":np.dot(L_Q_init, L_Q_init.T), 
							"B_init":B_init, "Sigma_int":np.dot(L_Sigma_init, L_Sigma_init.T)}
		learned_model_dict = {"Q_learned":Q_learned, 
							  "B_learned":B_learned, "Sigma_learned":Sigma_learned,
							  "Xs_val":Xs_val,
							  "As_val":As_val}
		log_ZSMC_dict = {"log_ZSMC_true":log_ZSMC_true_val, 
						 "log_ZSMC_trains": log_ZSMC_trains, 
						 "log_ZSMC_tests":log_ZSMC_tests}
		data_dict = {"hyperparams_dict":hyperparams_dict, 
					 "modelparams_dict":modelparams_dict, 
					 "training_data_dict":training_data_dict,
					 "true_model_dict":true_model_dict, 
					 "init_model_dict":init_model_dict, 
					 "learned_model_dict":learned_model_dict,
					 "log_ZSMC_dict":log_ZSMC_dict}
		with open(RLT_DIR + 'data.p', 'wb') as f:
			pickle.dump(data_dict, f)
		with open(RLT_DIR + 'data.json', 'w') as f:
			json.dump(data_dict, f, indent = 4, cls = NumpyEncoder)
		plot_losses(RLT_DIR, log_ZSMC_true_val, log_ZSMC_trains, log_ZSMC_tests)

	print("fin")
 