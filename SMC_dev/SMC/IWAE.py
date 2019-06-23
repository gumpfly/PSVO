import numpy as np
import tensorflow as tf
from tensorflow_probability import distributions as tfd

from SMC.SVO import SVO


class IWAE(SVO):
    def __init__(self, model, FLAGS, name="log_ZSMC"):
        SVO.__init__(self, model, FLAGS, name)
        self.IWAE = FLAGS.IWAE

    def resample_X(self, X, log_W, sample_size=()):
        assert sample_size == log_W.shape.as_list()[0]
        X_resampled = X
        return X_resampled
