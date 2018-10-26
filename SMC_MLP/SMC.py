import tensorflow as tf
import tensorflow.contrib.distributions as tfd

class SMC:
	def __init__(self, q, f, g, p,
				 n_particles,
				 use_stop_gradient = False,
				 name = "get_log_ZSMC"):
		self.q = q
		self.f = f
		self.g = g
		self.p = p
		self.n_particles = n_particles
		self.use_stop_gradient = use_stop_gradient
		self.name = name

	def get_log_ZSMC(self, obs):
		"""
		Input:
			obs.shape = (batch_size, time, Dy)
		Output:
			log_ZSMC: shape = scalar
			log: stuff to debug
		"""
		with tf.name_scope(self.name):
			batch_size, time, Dy = obs.get_shape().as_list()

			Xs = []
			log_Ws = []
			Ws = []
			fs = []
			gs = []
			qs = []
			ps = []

			# time = 1
			X = self.q.sample(None, name = 'X0')
			q_uno_log_probs = self.q.log_prob(None, X, name = 'q_uno_probs')
			f_nu_log_probs  = self.f.log_prob(None, X, name = 'f_nu_probs')
			g_uno_log_probs = self.g.log_prob(X, obs[:,0], name = 'g_uno_probs')
			
			log_W = tf.add(f_nu_log_probs, g_uno_log_probs - q_uno_log_probs, name = 'log_W_0')
			W = tf.exp(log_W, name = 'W_0')
			log_ZSMC = tf.log(tf.reduce_mean(W, axis = 0, name = 'W_0_mean'), name = 'log_ZSMC_0')

			Xs.append(X)
			log_Ws.append(log_W)
			Ws.append(W)
			fs.append(f_nu_log_probs)
			gs.append(g_uno_log_probs)
			qs.append(q_uno_log_probs)
			ps.append(tf.zeros((self.n_particles, batch_size)))

			for t in range(1, time):

				# W_{t-1} = W_{t-1} * p(y_t | X_{t-1})
				# k = p.posterior(X, obs[t], name = 'p_{}'.format(t))
				k = tf.ones((self.n_particles, batch_size), dtype = tf.float32, name = 'p_{}'.format(t))
				log_k = tf.log(k)
				log_W = log_W + log_k
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
				
				X = self.q.sample(X_prev, name = 'q_{}_sample'.format(t))
				q_t_log_probs = self.q.log_prob(X_prev, X, name = 'q_{}_log_probs'.format(t))
				f_t_log_probs  = self.f.log_prob(X_prev, X, name = 'f_{}_log_probs'.format(t))
				g_t_log_probs = self.g.log_prob(X, obs[:,t], name = 'g_{}_log_probs'.format(t))

				log_W = tf.add(f_t_log_probs - log_k, g_t_log_probs - q_t_log_probs, name = 'log_W_{}'.format(t))
				W = tf.exp(log_W, name = 'W_{}'.format(t))
				log_ZSMC += tf.log(tf.reduce_mean(W, axis = 0, name = 'W_0_mean'), name = 'log_ZSMC_{}'.format(t))

				Xs.append(X)
				Ws.append(W)
				log_Ws.append(log_W)
				fs.append(f_t_log_probs)
				gs.append(g_t_log_probs)
				qs.append(q_t_log_probs)
				ps.append(log_k)

			Xs = tf.stack(Xs)
			Ws = tf.stack(Ws)
			log_Ws = tf.stack(log_Ws)
			fs = tf.stack(fs)
			gs = tf.stack(gs)
			qs = tf.stack(qs)
			ps = tf.stack(ps)

			mean_log_ZSMC = tf.reduce_mean(log_ZSMC)

		return mean_log_ZSMC, [Xs, log_Ws, Ws, fs, gs, qs, ps]

	def tf_accuracy(self, obs_set, obs, log_ZSMC, sess, batch_size):
		"""
		used for evaluating true_log_ZSMC, train_log_ZSMC, test_log_ZSMC
		"""
		accuracy = 0
		for i in range(0, len(obs_set), batch_size):
			log_ZSMC_val = sess.run(log_ZSMC, feed_dict = {obs:obs_set[i:i+batch_size]})
			# print(i, log_ZSMC_val)
			accuracy += log_ZSMC_val
		return accuracy/(len(obs_set)/batch_size)