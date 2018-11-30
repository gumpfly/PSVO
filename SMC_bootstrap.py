import tensorflow as tf
import tensorflow.contrib.distributions as tfd
import numpy as np

class SMC:
	def __init__(self, q, f, g,
				 n_particles, batch_size, 
				 use_stop_gradient = False,
				 name = "get_log_ZSMC"):
		self.q = q
		self.f = f
		self.g = g
		self.n_particles = n_particles
		self.batch_size = batch_size
		self.use_stop_gradient = use_stop_gradient
		self.name = name

	def get_log_ZSMC(self, obs, x_0):
		"""
		Input:
			obs.shape = (batch_size, time, Dy)
		Output:
			log_ZSMC: shape = scalar
			log: stuff to debug
		"""
		with tf.name_scope(self.name):
			batch_size, time, Dy = obs.get_shape().as_list()
			batch_size, Dx = x_0.get_shape().as_list()

			Xs = []
			log_Ws = []
			Ws = []
			fs = []
			gs = []
			qs = []

			# time = 0
			if self.name == 'log_ZSMC_true':
				X = self.q.sample(None, name='X0')
				q_0_log_probs = self.q.log_prob(None, X, name = 'q_0_log_probs')
				f_0_log_probs = self.f.log_prob(None, X, name = 'f_0_log_probs')
			else:
				#x_0_y_0 = tf.concat([x_0, obs[:, 0]], axis = -1)
				#X, q_0_log_probs = self.q.sample_and_log_prob(x_0_y_0, name = 'q_0_log_probs')
				X, q_0_log_probs = self.q.sample_and_log_prob(x_0, name='q_0_log_probs')
				f_0_log_probs = self.f.log_prob(x_0, X, name = 'f_0_log_probs')
			g_0_log_probs = self.g.log_prob(X, obs[:,0], name = 'g_0_log_probs')
			
			log_W = tf.add(f_0_log_probs, g_0_log_probs - q_0_log_probs, name = 'log_W_0')
			W = tf.exp(log_W, name = 'W_0')
			log_ZSMC = tf.log(tf.reduce_mean(W, axis = 0, name = 'W_0_mean'), name = 'log_ZSMC_0')

			log_Ws.append(log_W)
			Ws.append(W)
			fs.append(f_0_log_probs)
			gs.append(g_0_log_probs)
			qs.append(q_0_log_probs)

			for t in range(1, time):
				log_W = tf.transpose(log_W)
				categorical = tfd.Categorical(logits = log_W, validate_args=True, 
											  name = 'Categorical_{}'.format(t))
				if self.use_stop_gradient:
					idx = tf.stop_gradient(categoriucal.sample(self.n_particles))	# (n_particles, batch_size)
				else:
					idx = categorical.sample(self.n_particles)

				# ugly stuff used to resample X
				ugly_stuff = tf.tile(tf.expand_dims(tf.range(batch_size), axis = 0), (self.n_particles, 1)) 	# (n_particles, batch_size)
				idx_expanded = tf.expand_dims(idx, axis = 2)											# (n_particles, batch_size, 1)
				ugly_expanded = tf.expand_dims(ugly_stuff, axis = 2)									# (n_particles, batch_size, 1)
				final_idx = tf.concat((idx_expanded, ugly_expanded), axis = 2)							# (n_particles, batch_size, 2)
				X_prev = tf.gather_nd(X, final_idx)														# (n_particles, batch_size, Dx)
				
				# change Xs to collect X after rather than before resampling
				Xs.append(X_prev)

				# (n_particles, batch_size, Dx)
				if self.name == 'log_ZSMC_true':
					X = self.q.sample(X_prev, name = 'q_{}_sample'.format(t))
					q_t_log_probs = self.q.log_prob(X_prev, X, name = 'q_{}_log_probs'.format(t))
				else:
					y_t_expanded = tf.tile(tf.expand_dims(obs[:, t], axis = 0), (self.n_particles, 1, 1))
					#X_prev_y_t = tf.concat([X_prev, y_t_expanded], axis = -1)
					#X, q_t_log_probs = self.q.sample_and_log_prob(X_prev_y_t, name = 'q_{}_log_probs'.format(t))
					X, q_t_log_probs = self.q.sample_and_log_prob(X_prev, name='q_{}_log_probs'.format(t))
				f_t_log_probs = self.f.log_prob(X_prev, X, name = 'f_{}_log_probs'.format(t))
				g_t_log_probs = self.g.log_prob(X, obs[:,t], name = 'g_{}_log_probs'.format(t))

				log_W = tf.add(f_t_log_probs, g_t_log_probs - q_t_log_probs, name = 'log_W_{}'.format(t))
				W = tf.exp(log_W, name = 'W_{}'.format(t))
				log_ZSMC += tf.log(tf.reduce_mean(W, axis = 0, name = 'W_0_mean'), name = 'log_ZSMC_{}'.format(t))

				Ws.append(W)
				log_Ws.append(log_W)
				fs.append(f_t_log_probs)
				gs.append(g_t_log_probs)
				qs.append(q_t_log_probs)

			# to make sure len(Xs) = time
			Xs.append(X)


			Xs = tf.stack(Xs)
			Ws = tf.stack(Ws)
			log_Ws = tf.stack(log_Ws)
			fs = tf.stack(fs)
			gs = tf.stack(gs)
			qs = tf.stack(qs)

			mean_log_ZSMC = tf.reduce_mean(log_ZSMC)

		return mean_log_ZSMC, [Xs, log_Ws, Ws, fs, gs, qs]


	def plot_flow(self, sess, Xdata, obs, obs_set, x_0, hidden_set, epoch, figsize=(13,13), newfig=True, RLT_DIR=None):

		with tf.name_scope(self.name):
			Dx = Xdata.shape[-1]

			Xdata = sess.run(Xdata, feed_dict={obs:obs_set[0:self.batch_size],
					   x_0:[hidden[0] for hidden in hidden_set[0:self.batch_size]]})


			Xdata = np.average(Xdata, axis=1)
			print("Xdata.shape ", Xdata.shape)
			import matplotlib.pyplot as plt
		
			plt.ion
			plt.figure(figsize=figsize)
			for p in range(self.batch_size):
				plt.plot(Xdata[:,p,0], Xdata[:,p,1])
				plt.scatter(Xdata[0,p,0], Xdata[0,p,1])
			axes = plt.gca()

			print("axes.get_xlim", axes.get_xlim)
			x1range, x2range = axes.get_xlim(), axes.get_ylim()
			print("x1range, x2range", x1range, x2range)


			s = int(5 * max(abs(x1range[0]) + abs(x1range[1]), abs(x2range[0]) + abs(x2range[1])) / 3)
			lattice = self.define2Dlattice(x1range,x2range)
			nextX = self.f.get_mean(tf.constant(lattice, dtype=tf.float32))

			nextX = sess.run(nextX)

			X = lattice


			plt.quiver(X[:,:,0], X[:,:,1], nextX[:,:,0] - X[:,:,0], nextX[:,:,1] - X[:,:,1], scale=s)
			plt.savefig(RLT_DIR + "Flow {}".format(epoch))
			#plt.show()



	@staticmethod
	def define2Dlattice(x1range=(-20.0, 20.0), x2range=(-20.0, 20.)):

		x1coords = np.linspace(x1range[0], x1range[1])
		x2coords = np.linspace(x2range[0], x2range[1])

		Xlattice = np.stack(np.meshgrid(x1coords,x2coords), axis=2)
		return Xlattice



	def tf_accuracy(self, sess, log_ZSMC, obs, obs_set, x_0, hidden_set):
		"""
		used for evaluating true_log_ZSMC, train_log_ZSMC, test_log_ZSMC
		"""
		accuracy = 0
		for i in range(0, len(obs_set), self.batch_size):
			log_ZSMC_val = sess.run(log_ZSMC, feed_dict = {obs:obs_set[i:i+self.batch_size], 
														   x_0:[hidden[0] for hidden in hidden_set[i:i+self.batch_size]]})
			# print(i, log_ZSMC_val)
			accuracy += log_ZSMC_val
		return accuracy/(len(obs_set)/self.batch_size)
